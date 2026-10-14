using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.Json.Nodes;
using CodeWalker.GameFiles;
using CodeWalker.Utils;

namespace GtaBridge;

public sealed class PedGlbBuilder
{
    private static readonly uint DIFFUSE_SAMPLER = JenkHash.GenHash("diffusesampler");

    private readonly PedSkeletonInfo skeleton;
    private readonly GameArchive archive;
    private readonly List<RpfFileEntry> folderEntries;
    private readonly GlbWriter writer = new GlbWriter();
    private readonly Dictionary<string, int> materialByTexture = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, TextureDictionary> loadedYtds = new Dictionary<string, TextureDictionary>(StringComparer.OrdinalIgnoreCase);

    public PedGlbBuilder(PedSkeletonInfo skeleton, GameArchive archive, List<RpfFileEntry> folderEntries)
    {
        this.skeleton = skeleton;
        this.archive = archive;
        this.folderEntries = folderEntries;
        AddSkeletonNodes();
    }

    private void AddSkeletonNodes()
    {
        Bone[] bones = skeleton.Bones;
        for (int i = 0; i < bones.Length; i++)
        {
            Bone bone = bones[i];
            JsonObject node = new JsonObject
            {
                ["name"] = bone.Name,
                ["translation"] = new JsonArray(bone.Translation.X, bone.Translation.Y, bone.Translation.Z),
                ["rotation"] = new JsonArray(bone.Rotation.X, bone.Rotation.Y, bone.Rotation.Z, bone.Rotation.W),
                ["scale"] = new JsonArray(bone.Scale.X, bone.Scale.Y, bone.Scale.Z),
                ["extras"] = new JsonObject { ["tag"] = bone.Tag, ["index"] = i },
            };
            int[] children = Enumerable.Range(0, bones.Length).Where(c => bones[c].ParentIndex == i).ToArray();
            if (children.Length > 0)
            {
                node["children"] = new JsonArray(children.Select(c => (JsonNode)c).ToArray());
            }
            writer.Nodes.Add(node);
        }

        int rootIndex = 0;
        for (int i = 0; i < bones.Length; i++)
        {
            if (bones[i].ParentIndex >= 0) continue;
            writer.SceneNodes.Add(i);
            rootIndex = i;
        }

        float[] inverseBind = new float[bones.Length * 16];
        for (int i = 0; i < bones.Length; i++)
        {
            Matrix4x4.Invert(skeleton.World[i], out Matrix4x4 inverse);
            WriteMatrix(inverseBind, i * 16, inverse);
        }

        int ibm = writer.AddMatrices(inverseBind);
        writer.Skins.Add(new JsonObject
        {
            ["inverseBindMatrices"] = ibm,
            ["joints"] = new JsonArray(Enumerable.Range(0, bones.Length).Select(i => (JsonNode)i).ToArray()),
            ["skeleton"] = rootIndex,
        });
    }

    public void AddComponent(YddFile ydd, string component)
    {
        if (ydd?.Drawables == null) return;

        JsonArray primitives = new JsonArray();
        foreach (Drawable drawable in ydd.Drawables)
        {
            DrawableModel[] models = drawable?.DrawableModels?.High;
            if (models == null) continue;

            foreach (DrawableModel model in models)
            {
                if (model?.Geometries == null) continue;
                foreach (DrawableGeometry geometry in model.Geometries)
                {
                    JsonObject primitive = BuildPrimitive(geometry);
                    if (primitive != null) primitives.Add(primitive);
                }
            }
        }

        if (primitives.Count == 0) return;

        writer.Meshes.Add(new JsonObject { ["name"] = component, ["primitives"] = primitives });
        writer.Nodes.Add(new JsonObject { ["name"] = component, ["mesh"] = writer.Meshes.Count - 1, ["skin"] = 0 });
        writer.SceneNodes.Add(writer.Nodes.Count - 1);
    }

    private JsonObject BuildPrimitive(DrawableGeometry geometry)
    {
        VertexData vertexData = geometry.VertexData;
        ushort[] indices = geometry.IndexBuffer?.Indices;
        if (vertexData?.VertexBytes == null || indices == null) return null;

        VertexReader reader = new VertexReader(vertexData);
        int count = vertexData.VertexCount;
        float[] positions = new float[count * 3];
        float[] normals = new float[count * 3];
        float[] uvs = new float[count * 2];
        ushort[] joints = new ushort[count * 4];
        float[] weights = new float[count * 4];

        for (int v = 0; v < count; v++)
        {
            reader.Read(v, VertexSemantics.Position, positions, v * 3, 3);
            reader.Read(v, VertexSemantics.Normal, normals, v * 3, 3);
            reader.Read(v, VertexSemantics.TexCoord0, uvs, v * 2, 2);
            ReadSkin(reader, geometry, v, joints, weights);
        }

        JsonObject attributes = new JsonObject
        {
            ["POSITION"] = writer.AddFloats(positions, 3, true),
            ["NORMAL"] = writer.AddFloats(NormalizeAll(normals), 3, false),
            ["TEXCOORD_0"] = writer.AddFloats(uvs, 2, false),
            ["JOINTS_0"] = writer.AddJoints(joints),
            ["WEIGHTS_0"] = writer.AddFloats(weights, 4, false),
        };

        JsonObject primitive = new JsonObject
        {
            ["attributes"] = attributes,
            ["indices"] = writer.AddIndices(indices),
        };

        int? material = ResolveMaterial(geometry.Shader);
        if (material.HasValue) primitive["material"] = material.Value;
        return primitive;
    }

    // Blend indices point into the geometry's BoneIds table when present, else straight into the skeleton.
    private void ReadSkin(VertexReader reader, DrawableGeometry geometry, int vertex, ushort[] joints, float[] weights)
    {
        byte[] rawIndices = reader.ReadBytes(vertex, VertexSemantics.BlendIndices);
        byte[] rawWeights = reader.ReadBytes(vertex, VertexSemantics.BlendWeights);
        if (rawIndices == null || rawWeights == null)
        {
            weights[vertex * 4] = 1f;
            return;
        }

        float sum = 0f;
        for (int k = 0; k < 4; k++)
        {
            int local = rawIndices[k];
            int bone = geometry.BoneIds != null && local < geometry.BoneIds.Length ? geometry.BoneIds[local] : local;
            if (bone >= skeleton.Bones.Length) bone = 0;

            joints[vertex * 4 + k] = (ushort)bone;
            weights[vertex * 4 + k] = rawWeights[k] / 255f;
            sum += weights[vertex * 4 + k];
        }

        if (sum <= 0f)
        {
            weights[vertex * 4] = 1f;
            return;
        }
        for (int k = 0; k < 4; k++) weights[vertex * 4 + k] /= sum;
    }

    private int? ResolveMaterial(ShaderFX shader)
    {
        string textureName = DiffuseTextureName(shader);
        if (textureName == null) return null;
        if (materialByTexture.TryGetValue(textureName, out int existing)) return existing;

        Texture texture = FindTexture(textureName);
        JsonObject pbr = new JsonObject { ["metallicFactor"] = 0.0, ["roughnessFactor"] = 0.8 };
        if (texture != null)
        {
            byte[] rgba = SwapRedBlue(DDSIO.GetPixels(texture, 0));
            byte[] png = PngEncoder.EncodeRgba(rgba, texture.Width, texture.Height);
            pbr["baseColorTexture"] = new JsonObject { ["index"] = writer.AddPngImage(png, textureName) };
        }

        writer.Materials.Add(new JsonObject
        {
            ["name"] = textureName,
            ["pbrMetallicRoughness"] = pbr,
            ["alphaMode"] = "OPAQUE",
            ["doubleSided"] = true,
        });
        materialByTexture[textureName] = writer.Materials.Count - 1;
        return writer.Materials.Count - 1;
    }

    // DDSIO hands back BGRA for the block-compressed formats ped textures use.
    private static byte[] SwapRedBlue(byte[] pixels)
    {
        for (int i = 0; i + 3 < pixels.Length; i += 4)
        {
            (pixels[i], pixels[i + 2]) = (pixels[i + 2], pixels[i]);
        }
        return pixels;
    }

    private static string DiffuseTextureName(ShaderFX shader)
    {
        ShaderParametersBlock parameters = shader?.ParametersList;
        if (parameters?.Parameters == null || parameters.Hashes == null) return null;

        for (int i = 0; i < parameters.Parameters.Length && i < parameters.Hashes.Length; i++)
        {
            if ((uint)parameters.Hashes[i] != DIFFUSE_SAMPLER) continue;
            if (parameters.Parameters[i].Data is TextureBase texture) return texture.Name;
        }
        return null;
    }

    private Texture FindTexture(string name)
    {
        string prefix = name.Split('_')[0];
        uint hash = JenkHash.GenHash(name.ToLowerInvariant());
        foreach (RpfFileEntry entry in folderEntries.Where(e => e.Name.EndsWith(".ytd", StringComparison.OrdinalIgnoreCase)
                                                             && e.Name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)))
        {
            TextureDictionary dictionary = LoadYtd(entry);
            if (dictionary?.Dict == null) continue;
            if (dictionary.Dict.TryGetValue(hash, out Texture texture)) return texture;
        }
        return null;
    }

    private TextureDictionary LoadYtd(RpfFileEntry entry)
    {
        if (loadedYtds.TryGetValue(entry.Path, out TextureDictionary cached)) return cached;

        TextureDictionary dictionary = archive.Load<YtdFile>(entry)?.TextureDict;
        loadedYtds[entry.Path] = dictionary;
        return dictionary;
    }

    public void Save(string path)
    {
        writer.Save(path);
    }

    private static float[] NormalizeAll(float[] normals)
    {
        for (int i = 0; i < normals.Length; i += 3)
        {
            Vector3 n = new Vector3(normals[i], normals[i + 1], normals[i + 2]);
            float length = n.Length();
            n = length > 1e-6f ? n / length : Vector3.UnitZ;
            normals[i] = n.X;
            normals[i + 1] = n.Y;
            normals[i + 2] = n.Z;
        }
        return normals;
    }

    private static void WriteMatrix(float[] target, int offset, Matrix4x4 m)
    {
        float[] values =
        {
            m.M11, m.M12, m.M13, m.M14,
            m.M21, m.M22, m.M23, m.M24,
            m.M31, m.M32, m.M33, m.M34,
            m.M41, m.M42, m.M43, m.M44,
        };
        Array.Copy(values, 0, target, offset, 16);
    }
}

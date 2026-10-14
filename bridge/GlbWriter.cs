using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;

namespace GtaBridge;

// Minimal glTF 2.0 binary writer: just enough for a skinned, textured ped.
public sealed class GlbWriter
{
    private const int ARRAY_BUFFER = 34962;
    private const int ELEMENT_ARRAY_BUFFER = 34963;
    private const int FLOAT = 5126;
    private const int UNSIGNED_BYTE = 5121;
    private const int UNSIGNED_SHORT = 5123;

    private readonly MemoryStream binary = new MemoryStream();
    private readonly JsonArray bufferViews = new JsonArray();
    private readonly JsonArray accessors = new JsonArray();

    public JsonArray Nodes { get; } = new JsonArray();
    public JsonArray Meshes { get; } = new JsonArray();
    public JsonArray Materials { get; } = new JsonArray();
    public JsonArray Textures { get; } = new JsonArray();
    public JsonArray Images { get; } = new JsonArray();
    public JsonArray Skins { get; } = new JsonArray();
    public JsonArray SceneNodes { get; } = new JsonArray();

    public int AddFloats(float[] data, int components, bool withBounds, int? target = ARRAY_BUFFER)
    {
        byte[] bytes = new byte[data.Length * 4];
        Buffer.BlockCopy(data, 0, bytes, 0, bytes.Length);
        int view = AddView(bytes, target);

        JsonObject accessor = new JsonObject
        {
            ["bufferView"] = view,
            ["componentType"] = FLOAT,
            ["count"] = data.Length / components,
            ["type"] = TypeName(components),
        };
        if (withBounds)
        {
            accessor["min"] = BoundArray(data, components, Math.Min);
            accessor["max"] = BoundArray(data, components, Math.Max);
        }
        accessors.Add(accessor);
        return accessors.Count - 1;
    }

    public int AddMatrices(float[] data)
    {
        int view = AddView(ToBytes(data), null);
        accessors.Add(new JsonObject
        {
            ["bufferView"] = view,
            ["componentType"] = FLOAT,
            ["count"] = data.Length / 16,
            ["type"] = "MAT4",
        });
        return accessors.Count - 1;
    }

    public int AddJoints(ushort[] data)
    {
        byte[] bytes = new byte[data.Length * 2];
        Buffer.BlockCopy(data, 0, bytes, 0, bytes.Length);
        int view = AddView(bytes, ARRAY_BUFFER);
        accessors.Add(new JsonObject
        {
            ["bufferView"] = view,
            ["componentType"] = UNSIGNED_SHORT,
            ["count"] = data.Length / 4,
            ["type"] = "VEC4",
        });
        return accessors.Count - 1;
    }

    public int AddIndices(ushort[] data)
    {
        byte[] bytes = new byte[data.Length * 2];
        Buffer.BlockCopy(data, 0, bytes, 0, bytes.Length);
        int view = AddView(bytes, ELEMENT_ARRAY_BUFFER);
        accessors.Add(new JsonObject
        {
            ["bufferView"] = view,
            ["componentType"] = UNSIGNED_SHORT,
            ["count"] = data.Length,
            ["type"] = "SCALAR",
        });
        return accessors.Count - 1;
    }

    public int AddPngImage(byte[] png, string name)
    {
        int view = AddView(png, null);
        Images.Add(new JsonObject { ["bufferView"] = view, ["mimeType"] = "image/png", ["name"] = name });
        Textures.Add(new JsonObject { ["source"] = Images.Count - 1 });
        return Textures.Count - 1;
    }

    public void Save(string path)
    {
        JsonObject root = new JsonObject
        {
            ["asset"] = new JsonObject { ["version"] = "2.0", ["generator"] = "gtabridge" },
            ["scene"] = 0,
            ["scenes"] = new JsonArray(new JsonObject { ["nodes"] = SceneNodes }),
            ["nodes"] = Nodes,
            ["meshes"] = Meshes,
            ["skins"] = Skins,
            ["accessors"] = accessors,
            ["bufferViews"] = bufferViews,
            ["buffers"] = new JsonArray(new JsonObject { ["byteLength"] = binary.Length }),
        };
        if (Materials.Count > 0) root["materials"] = Materials;
        if (Images.Count > 0)
        {
            root["images"] = Images;
            root["textures"] = Textures;
            root["samplers"] = new JsonArray(new JsonObject { ["magFilter"] = 9729, ["minFilter"] = 9987 });
        }

        byte[] json = Pad(Encoding.UTF8.GetBytes(root.ToJsonString()), 0x20);
        byte[] bin = Pad(binary.ToArray(), 0);

        using FileStream file = File.Create(path);
        using BinaryWriter writer = new BinaryWriter(file);
        writer.Write(0x46546C67u);
        writer.Write(2u);
        writer.Write((uint)(12 + 8 + json.Length + 8 + bin.Length));
        writer.Write((uint)json.Length);
        writer.Write(0x4E4F534Au);
        writer.Write(json);
        writer.Write((uint)bin.Length);
        writer.Write(0x004E4942u);
        writer.Write(bin);
    }

    private int AddView(byte[] bytes, int? target)
    {
        while (binary.Length % 4 != 0) binary.WriteByte(0);

        JsonObject view = new JsonObject
        {
            ["buffer"] = 0,
            ["byteOffset"] = binary.Length,
            ["byteLength"] = bytes.Length,
        };
        if (target.HasValue) view["target"] = target.Value;

        binary.Write(bytes, 0, bytes.Length);
        bufferViews.Add(view);
        return bufferViews.Count - 1;
    }

    private static byte[] ToBytes(float[] data)
    {
        byte[] bytes = new byte[data.Length * 4];
        Buffer.BlockCopy(data, 0, bytes, 0, bytes.Length);
        return bytes;
    }

    private static JsonArray BoundArray(float[] data, int components, Func<float, float, float> pick)
    {
        float[] bound = data.Take(components).ToArray();
        for (int i = components; i < data.Length; i++)
        {
            bound[i % components] = pick(bound[i % components], data[i]);
        }
        return new JsonArray(bound.Select(value => (JsonNode)value).ToArray());
    }

    private static string TypeName(int components) => components switch
    {
        1 => "SCALAR",
        2 => "VEC2",
        3 => "VEC3",
        4 => "VEC4",
        _ => throw new ArgumentOutOfRangeException(nameof(components)),
    };

    private static byte[] Pad(byte[] data, byte filler)
    {
        int padded = (data.Length + 3) & ~3;
        if (padded == data.Length) return data;

        byte[] result = Enumerable.Repeat(filler, padded).ToArray();
        Buffer.BlockCopy(data, 0, result, 0, data.Length);
        return result;
    }
}

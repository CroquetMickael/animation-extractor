using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using CodeWalker.GameFiles;

namespace GtaBridge;

public static partial class Commands
{
    // Freemode torso skin lives in jbib (component 11); uppr only carries the arms.
    private static readonly string[] DEFAULT_COMPONENTS = { "head", "uppr", "jbib", "lowr", "feet", "hand" };

    public static int ExportPed(Dictionary<string, string> options)
    {
        GameArchive archive = GameArchive.Open(Require(options, "gta"));
        string ped = Require(options, "ped").ToLowerInvariant();
        string outDir = Require(options, "out");
        string[] components = Optional(options, "components", string.Join(",", DEFAULT_COMPONENTS)).Split(',');
        Directory.CreateDirectory(outDir);

        string baseFolder = $"streamedpeds_mp.rpf\\{ped}\\";
        RpfFileEntry yftEntry = archive.Find($"streamedpeds_mp\\.rpf\\\\{Regex.Escape(ped)}\\.yft$").FirstOrDefault();
        if (yftEntry == null) throw new InvalidOperationException($"{ped}.yft not found");

        YftFile yft = archive.Load<YftFile>(yftEntry);
        Skeleton skeleton = yft?.Fragment?.Drawable?.Skeleton;
        if (skeleton?.Bones?.Items == null) throw new InvalidOperationException($"{ped}.yft has no skeleton");

        Bone[] bones = skeleton.Bones.Items;
        PedSkeletonInfo info = PedSkeletonInfo.Build(bones);
        File.WriteAllText(Path.Combine(outDir, $"{ped}.skeleton.json"), info.ToJson(ped));

        List<RpfFileEntry> folderEntries = archive.Find(Regex.Escape(baseFolder)).ToList();
        PedGlbBuilder builder = new PedGlbBuilder(info, archive, folderEntries);
        foreach (string component in components)
        {
            RpfFileEntry ydd = folderEntries.FirstOrDefault(entry =>
                Regex.IsMatch(entry.Name, $"^{Regex.Escape(component)}_000_[a-z]+\\.ydd$", RegexOptions.IgnoreCase));
            if (ydd == null)
            {
                Console.Error.WriteLine($"component {component} not found, skipped");
                continue;
            }
            builder.AddComponent(archive.Load<YddFile>(ydd), component);
        }

        string glbPath = Path.Combine(outDir, $"{ped}.glb");
        builder.Save(glbPath);
        Console.WriteLine($"ok bones={bones.Length} glb={glbPath}");
        return 0;
    }

    // --in reads a loose .ycd (our own exports, checked the way the game will read them); else --dict from GTA V.
    private static YcdFile LoadClipDictionary(Dictionary<string, string> options)
    {
        if (options.TryGetValue("in", out string path)) return YcdIo.LoadLooseYcd(path);

        GameArchive archive = GameArchive.Open(Require(options, "gta"));
        string dict = Require(options, "dict");
        RpfFileEntry entry = archive.FindLast($"{dict}.ycd");
        if (entry == null) throw new InvalidOperationException($"{dict}.ycd not found");
        return archive.Load<YcdFile>(entry);
    }

    public static int DumpClip(Dictionary<string, string> options)
    {
        YcdFile ycd = LoadClipDictionary(options);
        string clipName = Require(options, "clip");
        ClipMapEntry clipEntry = ycd.ClipMapEntries.FirstOrDefault(c =>
            string.Equals(c?.Clip?.ShortName, clipName, StringComparison.OrdinalIgnoreCase));
        Animation[] animations = clipEntry?.Clip switch
        {
            ClipAnimation single when single.Animation != null => new[] { single.Animation },
            ClipAnimationList list => list.Animations?.Data?.Select(a => a?.Animation).Where(a => a != null).ToArray(),
            _ => null,
        };
        if (animations == null || animations.Length == 0)
        {
            string available = string.Join(", ", ycd.ClipMapEntries.Select(c => c?.Clip?.ShortName));
            throw new InvalidOperationException($"clip {clipName} not found. Available: {available}");
        }

        File.WriteAllText(Require(options, "out"), ClipDump.ToJson(clipEntry.Clip.ShortName, animations));
        return 0;
    }
}

public sealed class PedSkeletonInfo
{
    public Bone[] Bones { get; private init; }
    public Matrix4x4[] World { get; private init; }

    public static PedSkeletonInfo Build(Bone[] bones)
    {
        Matrix4x4[] world = new Matrix4x4[bones.Length];
        bool[] done = new bool[bones.Length];
        for (int i = 0; i < bones.Length; i++)
        {
            Resolve(bones, world, done, i);
        }
        return new PedSkeletonInfo { Bones = bones, World = world };
    }

    public static Matrix4x4 Local(Bone bone)
    {
        Quaternion rotation = new Quaternion(bone.Rotation.X, bone.Rotation.Y, bone.Rotation.Z, bone.Rotation.W);
        Vector3 translation = new Vector3(bone.Translation.X, bone.Translation.Y, bone.Translation.Z);
        Vector3 scale = new Vector3(bone.Scale.X, bone.Scale.Y, bone.Scale.Z);
        return Matrix4x4.CreateScale(scale) * Matrix4x4.CreateFromQuaternion(rotation) * Matrix4x4.CreateTranslation(translation);
    }

    private static void Resolve(Bone[] bones, Matrix4x4[] world, bool[] done, int index)
    {
        if (done[index]) return;

        Matrix4x4 local = Local(bones[index]);
        int parent = bones[index].ParentIndex;
        if (parent >= 0 && parent < bones.Length)
        {
            Resolve(bones, world, done, parent);
            world[index] = local * world[parent];
        }
        else
        {
            world[index] = local;
        }
        done[index] = true;
    }

    public string ToJson(string ped)
    {
        JsonArray list = new JsonArray();
        for (int i = 0; i < Bones.Length; i++)
        {
            Bone bone = Bones[i];
            Matrix4x4 w = World[i];
            list.Add(new JsonObject
            {
                ["index"] = i,
                ["name"] = bone.Name,
                ["tag"] = bone.Tag,
                ["parent"] = bone.ParentIndex,
                ["flags"] = (int)bone.Flags,
                ["t"] = new JsonArray(bone.Translation.X, bone.Translation.Y, bone.Translation.Z),
                ["r"] = new JsonArray(bone.Rotation.X, bone.Rotation.Y, bone.Rotation.Z, bone.Rotation.W),
                ["s"] = new JsonArray(bone.Scale.X, bone.Scale.Y, bone.Scale.Z),
                ["worldPos"] = new JsonArray(w.M41, w.M42, w.M43),
            });
        }
        JsonObject root = new JsonObject { ["ped"] = ped, ["upAxis"] = "Z", ["bones"] = list };
        return root.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using CodeWalker.GameFiles;

namespace GtaBridge;

public static partial class Commands
{
    public static int InspectYdd(Dictionary<string, string> options)
    {
        GameArchive archive = GameArchive.Open(Require(options, "gta"));
        RpfFileEntry entry = archive.Find(Require(options, "pattern")).FirstOrDefault();
        if (entry == null) return 1;
        YddFile ydd = archive.Load<YddFile>(entry);
        foreach (Drawable drawable in ydd.Drawables)
        {
            Bone[] bones = drawable.Skeleton?.Bones?.Items;
            Console.WriteLine($"{entry.Path} skeleton={(bones == null ? "none" : bones.Length.ToString())}");
            if (bones != null) Console.WriteLine(string.Join(",", bones.Take(12).Select(b => $"{b.Name}:{b.Tag}")));
            foreach (DrawableModel model in drawable.DrawableModels?.High ?? new DrawableModel[0])
            {
                foreach (DrawableGeometry g in model.Geometries)
                {
                    VertexDeclaration info = g.VertexData.Info;
                    Console.WriteLine($" geom verts={g.VertexData.VertexCount} boneIds={(g.BoneIds == null ? "null" : g.BoneIds.Length + ":" + string.Join(",", g.BoneIds.Take(10)))} wType={info.GetComponentType(1)} iType={info.GetComponentType(2)} skelBinding={model.SkeletonBinding:X}");
                }
            }
        }
        return 0;
    }
}

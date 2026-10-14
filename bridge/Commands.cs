using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using CodeWalker.GameFiles;

namespace GtaBridge;

public static partial class Commands
{
    public static int Find(Dictionary<string, string> options)
    {
        GameArchive archive = GameArchive.Open(Require(options, "gta"));
        foreach (RpfFileEntry entry in archive.Find(Require(options, "pattern")))
        {
            Console.WriteLine(entry.Path);
        }
        return 0;
    }

    public static int Extract(Dictionary<string, string> options)
    {
        GameArchive archive = GameArchive.Open(Require(options, "gta"));
        if (options.TryGetValue("pattern", out string pattern)) return ExtractAll(archive, pattern, Require(options, "outdir"));

        string name = Require(options, "name");
        RpfFileEntry entry = archive.FindLast(name);
        if (entry == null)
        {
            Console.Error.WriteLine($"{name} not found");
            return 1;
        }

        byte[] data = archive.Extract(entry);
        File.WriteAllBytes(Require(options, "out"), data);
        Console.WriteLine(entry.Path);
        return 0;
    }

    // Same-named files from different archives (every DLC's clip_sets.xml) land side by side, prefixed by their archive path.
    private static int ExtractAll(GameArchive archive, string pattern, string outDir)
    {
        Directory.CreateDirectory(outDir);
        int count = 0;
        foreach (RpfFileEntry entry in archive.Find(pattern))
        {
            byte[] data = archive.Extract(entry);
            if (data == null) continue;
            string flat = string.Join("_", entry.Path.Split('\\').Where(part => part.Length > 0));
            File.WriteAllBytes(Path.Combine(outDir, flat), data);
            Console.WriteLine(entry.Path);
            count++;
        }
        return count > 0 ? 0 : 1;
    }

    public static int YcdToXml(Dictionary<string, string> options)
    {
        string input = Require(options, "in");
        YcdFile ycd = YcdIo.LoadLooseYcd(input);
        File.WriteAllText(Require(options, "out"), YcdXml.GetXml(ycd));
        return 0;
    }

    public static int XmlToYcd(Dictionary<string, string> options)
    {
        string xml = File.ReadAllText(Require(options, "in"));
        YcdFile ycd = XmlYcd.GetYcd(xml);
        byte[] data = ycd.Save();
        File.WriteAllBytes(Require(options, "out"), data);

        // Round-trip through the binary loader so a malformed export fails here, not in game.
        YcdFile check = YcdIo.LoadLooseYcd(Require(options, "out"));
        int clipCount = check.ClipMapEntries?.Length ?? 0;
        Console.WriteLine($"ok clips={clipCount} bytes={data.Length}");
        return 0;
    }

    private static string Require(Dictionary<string, string> options, string key)
    {
        if (options.TryGetValue(key, out string value)) return value;
        throw new ArgumentException($"missing --{key}");
    }

    private static string Optional(Dictionary<string, string> options, string key, string fallback)
    {
        return options.TryGetValue(key, out string value) ? value : fallback;
    }
}

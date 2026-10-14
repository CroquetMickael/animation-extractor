using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using CodeWalker.GameFiles;

namespace GtaBridge;

// Opens the GTA V archives once; every command goes through this.
public sealed class GameArchive
{
    public RpfManager Manager { get; }

    private GameArchive(RpfManager manager)
    {
        Manager = manager;
    }

    public static GameArchive Open(string gtaFolder)
    {
        if (!File.Exists(Path.Combine(gtaFolder, "GTA5.exe")))
        {
            throw new InvalidOperationException($"GTA5.exe not found in {gtaFolder}");
        }

        GTA5Keys.LoadFromPath(gtaFolder, false, null);

        RpfManager manager = new RpfManager();
        manager.Init(gtaFolder, false, _ => { }, error => Console.Error.WriteLine($"[rpf] {error}"));
        return new GameArchive(manager);
    }

    public IEnumerable<RpfFileEntry> Find(string pattern)
    {
        Regex regex = new Regex(pattern, RegexOptions.IgnoreCase);
        return Manager.AllRpfs
            .SelectMany(rpf => rpf.AllEntries ?? new List<RpfEntry>())
            .OfType<RpfFileEntry>()
            .Where(entry => regex.IsMatch(entry.Path));
    }

    // Update/DLC archives override the base game; take the last match in load order.
    public RpfFileEntry FindLast(string fileName)
    {
        return Manager.AllRpfs
            .SelectMany(rpf => rpf.AllEntries ?? new List<RpfEntry>())
            .OfType<RpfFileEntry>()
            .LastOrDefault(entry => string.Equals(entry.Name, fileName, StringComparison.OrdinalIgnoreCase));
    }

    public T Load<T>(RpfFileEntry entry) where T : class, PackedFile, new()
    {
        return Manager.GetFile<T>(entry);
    }

    // Resources come out inflated and headerless; re-wrap them so the file is a standalone RSC7 like CodeWalker's export.
    public byte[] Extract(RpfFileEntry entry)
    {
        byte[] data = entry.File.ExtractFile(entry);
        if (data == null || entry is not RpfResourceFileEntry resource) return data;

        return ResourceBuilder.AddResourceHeader(resource, ResourceBuilder.Compress(data));
    }
}

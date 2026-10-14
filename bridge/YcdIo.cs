using System.IO;
using CodeWalker.GameFiles;

namespace GtaBridge;

public static class YcdIo
{
    public static YcdFile LoadLooseYcd(string path)
    {
        byte[] data = File.ReadAllBytes(path);
        RpfFileEntry entry = RpfFile.CreateResourceFileEntry(ref data, 0);
        entry.Name = Path.GetFileName(path);

        byte[] decompressed = ResourceBuilder.Decompress(data);
        YcdFile ycd = new YcdFile();
        ycd.Load(decompressed, entry);
        return ycd;
    }
}

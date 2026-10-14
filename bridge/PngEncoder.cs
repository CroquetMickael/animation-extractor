using System;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace GtaBridge;

public static class PngEncoder
{
    private static readonly uint[] CRC_TABLE = BuildCrcTable();

    public static byte[] EncodeRgba(byte[] rgba, int width, int height)
    {
        using MemoryStream output = new MemoryStream();
        output.Write(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A });

        byte[] header = new byte[13];
        WriteBigEndian(header, 0, (uint)width);
        WriteBigEndian(header, 4, (uint)height);
        header[8] = 8;
        header[9] = 6;
        WriteChunk(output, "IHDR", header);

        using MemoryStream compressed = new MemoryStream();
        using (ZLibStream zlib = new ZLibStream(compressed, CompressionLevel.Fastest, true))
        {
            int stride = width * 4;
            for (int y = 0; y < height; y++)
            {
                zlib.WriteByte(0);
                zlib.Write(rgba, y * stride, stride);
            }
        }
        WriteChunk(output, "IDAT", compressed.ToArray());
        WriteChunk(output, "IEND", Array.Empty<byte>());
        return output.ToArray();
    }

    private static void WriteChunk(Stream output, string type, byte[] data)
    {
        byte[] length = new byte[4];
        WriteBigEndian(length, 0, (uint)data.Length);
        output.Write(length);

        byte[] typeBytes = Encoding.ASCII.GetBytes(type);
        output.Write(typeBytes);
        output.Write(data);

        uint crc = Crc(Crc(0xFFFFFFFFu, typeBytes), data) ^ 0xFFFFFFFFu;
        byte[] crcBytes = new byte[4];
        WriteBigEndian(crcBytes, 0, crc);
        output.Write(crcBytes);
    }

    private static uint Crc(uint crc, byte[] data)
    {
        foreach (byte value in data)
        {
            crc = CRC_TABLE[(crc ^ value) & 0xFF] ^ (crc >> 8);
        }
        return crc;
    }

    private static uint[] BuildCrcTable()
    {
        uint[] table = new uint[256];
        for (uint n = 0; n < 256; n++)
        {
            uint c = n;
            for (int k = 0; k < 8; k++)
            {
                c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            }
            table[n] = c;
        }
        return table;
    }

    private static void WriteBigEndian(byte[] buffer, int offset, uint value)
    {
        buffer[offset] = (byte)(value >> 24);
        buffer[offset + 1] = (byte)(value >> 16);
        buffer[offset + 2] = (byte)(value >> 8);
        buffer[offset + 3] = (byte)value;
    }
}

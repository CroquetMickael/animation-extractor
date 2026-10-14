using System;
using CodeWalker.GameFiles;

namespace GtaBridge;

public sealed class VertexReader
{
    private readonly VertexData data;

    public VertexReader(VertexData data)
    {
        this.data = data;
    }

    private bool Has(VertexSemantics semantic) => ((data.Info.Flags >> (int)semantic) & 1) == 1;

    public void Read(int vertex, VertexSemantics semantic, float[] target, int offset, int count)
    {
        if (!Has(semantic)) return;

        int start = vertex * data.VertexStride + data.Info.GetComponentOffset((int)semantic);
        VertexComponentType type = data.Info.GetComponentType((int)semantic);
        byte[] bytes = data.VertexBytes;

        for (int i = 0; i < count; i++)
        {
            target[offset + i] = type switch
            {
                VertexComponentType.Float or VertexComponentType.Float2 or VertexComponentType.Float3 or VertexComponentType.Float4
                    => BitConverter.ToSingle(bytes, start + i * 4),
                VertexComponentType.Half2 or VertexComponentType.Half4
                    => (float)BitConverter.ToHalf(bytes, start + i * 2),
                VertexComponentType.Colour or VertexComponentType.UByte4
                    => bytes[start + i] / 255f,
                VertexComponentType.RGBA8SNorm
                    => (sbyte)bytes[start + i] / 127f,
                _ => 0f,
            };
        }
    }

    public byte[] ReadBytes(int vertex, VertexSemantics semantic)
    {
        if (!Has(semantic)) return null;

        int start = vertex * data.VertexStride + data.Info.GetComponentOffset((int)semantic);
        byte[] result = new byte[4];
        Array.Copy(data.VertexBytes, start, result, 0, 4);
        return result;
    }
}

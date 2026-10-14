using System.Collections.Generic;
using System.Text.Json.Nodes;
using CodeWalker.GameFiles;
using SharpDX;

namespace GtaBridge;

// Evaluates every track of a game clip per frame, so the viewer can play real GTA anims
// and we can check our conventions against Rockstar's data.
public static class ClipDump
{
    private const byte TRACK_BONE_ROTATION = 1;
    private const byte TRACK_MOVER_ROTATION = 6;

    public static string ToJson(string clipName, IEnumerable<Animation> animations)
    {
        JsonArray list = new JsonArray();
        foreach (Animation animation in animations)
        {
            list.Add(new JsonObject
            {
                ["frames"] = animation.Frames,
                ["duration"] = animation.Duration,
                ["tracks"] = DumpTracks(animation),
            });
        }

        JsonObject root = new JsonObject { ["clip"] = clipName, ["animations"] = list };
        return root.ToJsonString();
    }

    private static JsonArray DumpTracks(Animation animation)
    {
        JsonArray tracks = new JsonArray();
        AnimationBoneId[] boneIds = animation.BoneIds?.data_items ?? new AnimationBoneId[0];

        for (int b = 0; b < boneIds.Length; b++)
        {
            AnimationBoneId id = boneIds[b];
            bool isQuaternion = id.Track == TRACK_BONE_ROTATION || id.Track == TRACK_MOVER_ROTATION;
            JsonArray values = new JsonArray();

            for (int f = 0; f < animation.Frames; f++)
            {
                Animation.FramePosition position = new Animation.FramePosition { Frame0 = f, Frame1 = f, Alpha0 = 1f, Alpha1 = 0f };
                if (isQuaternion)
                {
                    Quaternion q = animation.EvaluateQuaternion(position, b, false);
                    values.Add(new JsonArray(q.X, q.Y, q.Z, q.W));
                }
                else
                {
                    Vector4 v = animation.EvaluateVector4(position, b, false);
                    values.Add(new JsonArray(v.X, v.Y, v.Z));
                }
            }

            tracks.Add(new JsonObject { ["bone"] = id.BoneId, ["track"] = id.Track, ["values"] = values });
        }
        return tracks;
    }
}

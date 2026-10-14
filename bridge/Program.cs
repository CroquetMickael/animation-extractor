using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading;

namespace GtaBridge;

public static class Program
{
    public static int Main(string[] args)
    {
        Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture;

        if (args.Length == 0)
        {
            PrintUsage();
            return 1;
        }

        Dictionary<string, string> options = ParseOptions(args);
        try
        {
            return args[0] switch
            {
                "find" => Commands.Find(options),
                "export-ped" => Commands.ExportPed(options),
                "extract" => Commands.Extract(options),
                "ycd-to-xml" => Commands.YcdToXml(options),
                "xml-to-ycd" => Commands.XmlToYcd(options),
                "dump-clip" => Commands.DumpClip(options),
                "inspect-ydd" => Commands.InspectYdd(options),
                _ => Fail($"unknown command {args[0]}"),
            };
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 2;
        }
    }

    private static int Fail(string message)
    {
        Console.Error.WriteLine(message);
        PrintUsage();
        return 1;
    }

    private static Dictionary<string, string> ParseOptions(string[] args)
    {
        Dictionary<string, string> options = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 1; i < args.Length; i++)
        {
            if (!args[i].StartsWith("--")) continue;

            string key = args[i].Substring(2);
            bool hasValue = i + 1 < args.Length && !args[i + 1].StartsWith("--");
            options[key] = hasValue ? args[++i] : "true";
        }
        return options;
    }

    private static void PrintUsage()
    {
        Console.Error.WriteLine("""
            gtabridge find        --gta <dir> --pattern <regex>
            gtabridge extract     --gta <dir> --name <file> --out <file>
            gtabridge export-ped  --gta <dir> --ped <model> --out <dir> [--components head_000_r,uppr_000_u,...]
            gtabridge dump-clip   --gta <dir> --dict <name> --clip <name> --out <json>
            gtabridge ycd-to-xml  --in <file.ycd> --out <file.ycd.xml>
            gtabridge xml-to-ycd  --in <file.ycd.xml> --out <file.ycd>
            """);
    }
}

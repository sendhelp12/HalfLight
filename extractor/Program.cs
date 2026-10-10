using System.Text.Json;
using CUE4Parse;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Versions;
using Serilog;

if (args.Length != 4) throw new ArgumentException("paks mapping object-path output-json");
Log.Logger = new LoggerConfiguration().WriteTo.Console().CreateLogger();
CUE4ParseLog.UseLogger(Log.Logger);
using var provider = new DefaultFileProvider(args[0], SearchOption.TopDirectoryOnly, new VersionContainer(EGame.GAME_UE5_4), StringComparer.OrdinalIgnoreCase);
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(args[1]);
provider.Initialize();
foreach (var archive in provider.UnloadedVfs) Console.WriteLine($"Archive {archive.Name}: encrypted={archive.IsEncrypted}, directory={archive.HasDirectoryIndex}, guid={archive.EncryptionKeyGuid}");
var mounted = provider.Mount();
if (mounted == 0 && Environment.GetEnvironmentVariable("HALFLIGHT_AES_CANDIDATES") is { } candidatesPath)
{
    var candidates=JsonSerializer.Deserialize<string[]>(File.ReadAllText(candidatesPath))!;
    foreach (var candidate in candidates)
    {
        mounted += provider.SubmitKey(new FGuid(), new FAesKey(candidate));
        if (mounted > 0) { Console.WriteLine("Locally scanned archive key validated by mounting the archive"); break; }
    }
}
Console.WriteLine($"Mounted {mounted} archives; indexed {provider.Files.Count} files");
if (args[2] == "--weapon-assets")
{
    var paths = provider.Files.Keys.Where(p => (p.Contains("/Weapons/", StringComparison.OrdinalIgnoreCase)
        || p.Contains("/Blueprints/GameLogic/Forge/", StringComparison.OrdinalIgnoreCase)
        || p.EndsWith("/ModularWeaponBP.uasset", StringComparison.OrdinalIgnoreCase))
        && p.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)).OrderBy(p => p).ToArray();
    if (mounted == 0 || paths.Length == 0) throw new Exception("No mounted weapon assets");
    File.WriteAllLines(args[3], paths);
    Console.WriteLine($"Listed {paths.Length} weapon asset paths; no asset buffers extracted");
    return;
}
if (args[2] == "--batch")
{
    var requests=JsonSerializer.Deserialize<Dictionary<string,string>[]>(File.ReadAllText(args[3]))!;
    foreach(var request in requests) Extract(request["source"],request["output"]);
    return;
}
Extract(args[2],args[3]);
void Extract(string source,string output)
{
if (source.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
{
    provider.ReadScriptData = true;
    var package = provider.LoadPackage(source);
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
    File.WriteAllText(output, Newtonsoft.Json.JsonConvert.SerializeObject(package.GetExports(), Newtonsoft.Json.Formatting.Indented));
    Console.WriteLine($"Read definition {source}");
    return;
}
var mesh = provider.LoadPackageObject<UStaticMesh>(source);
var lods = mesh.RenderData?.LODs ?? throw new Exception("No render data");
var lodIndex = Array.FindIndex(lods, lod => !lod.SkipLod);
if (lodIndex < 0) throw new Exception("No readable mesh LOD");
var lod = lods[lodIndex];
var positions = lod.PositionVertexBuffer!.Verts;
var vertices = positions.Select(p => new[] {p.X,p.Y,p.Z}).ToArray();
var normals = lod.VertexBuffer!.UV.Select(uv => new[] {uv.Normal[2].X,uv.Normal[2].Y,uv.Normal[2].Z}).ToArray();
var uvs = lod.VertexBuffer.UV.Select(uv => new[] {uv.UV[0].U,uv.UV[0].V}).ToArray();
var indices = lod.IndexBuffer!.Buffer ?? throw new Exception("No index buffer");
if (indices.Length % 3 != 0 || indices.Any(i => i>=vertices.Length)) throw new Exception("Invalid triangle indices");
var data = new {format="HalfLightStaticMesh1", source, engine="5.4", coordinates="Unreal native centimetres, X forward Y right Z up; no exporter coordinate conversion", lodIndex, vertices, normals, uvs, indices,
    sections=lod.Sections.Select(s => new {s.MaterialIndex,s.FirstIndex,s.NumTriangles}).ToArray()};
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
File.WriteAllText(output,JsonSerializer.Serialize(data));
Console.WriteLine($"Extracted {mesh.Name}: LOD {lodIndex}, {vertices.Length} vertices, {indices.Length/3} triangles");
}

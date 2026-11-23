using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
namespace ScoreForge.Desktop.Services;

public sealed class ApiFailure(int status,string message) : Exception(message)
{ public int Status { get; } = status; }
public sealed record ApiReply(int Status, JsonObject Data, long Milliseconds);
public sealed class ApiClient : IDisposable
{
    private readonly HttpClient http;
    private string csrf="";
    public string BaseUrl { get; }
    public JsonObject User { get; private set; } = new();
    public bool IsAdmin => User["role"]?.ToString()=="admin";
    public ApiClient(string url)
    {
        BaseUrl=url.TrimEnd('/');
        http=new HttpClient(new HttpClientHandler { CookieContainer=new CookieContainer(),UseCookies=true,UseProxy=false })
        { BaseAddress=new Uri(BaseUrl),Timeout=TimeSpan.FromSeconds(20) };
    }
    public async Task<ApiReply> RawAsync(string path,string method="GET",object? body=null)
    {
        // Only same-server API routes; the explorer cannot send session credentials elsewhere.
        if(!path.StartsWith("/api/",StringComparison.Ordinal)||path.Contains(":")||path.Contains("\\"))
            throw new ArgumentException("Choose a local /api/ endpoint.");
        using var request=new HttpRequestMessage(new HttpMethod(method),path);
        request.Headers.Add("X-CSRF-Token",csrf);
        if(method!="GET") request.Content=new StringContent(JsonSerializer.Serialize(body??new{}),Encoding.UTF8,"application/json");
        var watch=Stopwatch.StartNew();
        using var response=await http.SendAsync(request);
        var text=await response.Content.ReadAsStringAsync();
        var data=JsonNode.Parse(text) as JsonObject ?? new JsonObject();
        return new((int)response.StatusCode,data,watch.ElapsedMilliseconds);
    }
    public async Task<JsonObject> SendAsync(string path,string method="GET",object? body=null)
    {
        var r=await RawAsync(path,method,body);
        if(r.Status>=400)throw new ApiFailure(r.Status,r.Data["error"]?.ToString()??"Request failed.");
        return r.Data;
    }
    public async Task LoginAsync(string username,string password)
    {
        var result=await SendAsync("/api/login","POST",new{username,password});
        User=(JsonObject)result["user"]!.DeepClone();csrf=result["csrf"]!.ToString();
    }
    public async Task<byte[]> ExportAsync()
    {
        using var response=await http.GetAsync("/api/export");
        response.EnsureSuccessStatusCode();return await response.Content.ReadAsByteArrayAsync();
    }
    public void Dispose()=>http.Dispose();
}

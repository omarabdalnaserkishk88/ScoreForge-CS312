using System.Diagnostics;
namespace ScoreForge.Desktop.Services;
public static class Backend
{
    public static async Task<string> StartAsync()
    {
        var root=Path.Combine(AppContext.BaseDirectory,"backend");
        var script=Path.Combine(root,"desktop_host.py");
        if(!File.Exists(script))throw new FileNotFoundException("Build the solution first. Missing backend/desktop_host.py.");
        var errors=new List<string>();
        foreach(var launcher in new[]{"python","py"})
        {
            Process? process=null;
            try
            {
                var start=new ProcessStartInfo(launcher){WorkingDirectory=root,UseShellExecute=false,
                    RedirectStandardOutput=true,RedirectStandardError=true,CreateNoWindow=true};
                if(launcher=="py")start.ArgumentList.Add("-3");
                start.ArgumentList.Add("-u");start.ArgumentList.Add(script);
                start.ArgumentList.Add("--parent-pid");start.ArgumentList.Add(Environment.ProcessId.ToString());
                process=Process.Start(start)??throw new Exception("Python did not start.");
                // Drain stderr concurrently; never allow a full pipe to block the server.
                process.ErrorDataReceived+=(_,_)=>{};process.BeginErrorReadLine();
                using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(30));
                string? line;
                while((line=await process.StandardOutput.ReadLineAsync(timeout.Token))!=null)
                {
                    if(!line.StartsWith("READY "))continue;
                    var url=line[6..].Trim();
                    if(!Uri.TryCreate(url,UriKind.Absolute,out var uri)||uri.Host!="127.0.0.1"||uri.Scheme!="http")throw new Exception("Invalid backend address.");
                    // Keep the backend alive so another client/active round is not interrupted.
                    _=DrainAsync(process);
                    return url;
                }
                throw new Exception("Python exited before the server was ready.");
            }
            catch(Exception e)
            {
                errors.Add(launcher+": "+e.Message);
                try{if(process!=null&&!process.HasExited)process.Kill(true);}catch{}
                process?.Dispose();
            }
        }
        throw new Exception("Install Python 3.10+ with Add to PATH enabled.\n"+string.Join("\n",errors));
    }
    private static async Task DrainAsync(Process p)
    { try{while(await p.StandardOutput.ReadLineAsync()!=null){}await p.WaitForExitAsync();}catch{}finally{p.Dispose();} }
}

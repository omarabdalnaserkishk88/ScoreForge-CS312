using System.ComponentModel;
using ScoreForge.Desktop.Services;
namespace ScoreForge.Desktop.Forms;
public partial class LoginForm : Form
{
    private ApiClient? api;
    public LoginForm()
    {
        InitializeComponent();
        if(LicenseManager.UsageMode==LicenseUsageMode.Designtime)return;
        Shown+=async(_,_)=>await ConnectAsync();
        btnLogin.Click+=async(_,_)=>await LoginAsync();
        btnAdmin.Click+=(_,_)=>{txtUsername.Text="admin";txtPassword.Text="Admin@12345";};
        btnPlayer.Click+=(_,_)=>{txtUsername.Text="player1";txtPassword.Text="Player@12345";};
        btnRetry.Click+=async(_,_)=>await ConnectAsync();
        FormClosed+=(_,_)=>api?.Dispose();
    }
    private async Task ConnectAsync()
    {
        btnRetry.Enabled=false;btnLogin.Enabled=false;lblError.Text="Starting your local HTTP server...";
        try
        {
            api?.Dispose();api=new ApiClient(await Backend.StartAsync());
            lblConnection.Text="HTTP connected · "+api.BaseUrl;
            lblError.Text="";btnLogin.Enabled=true;
        }
        catch(Exception e){lblError.Text=e.Message;}
        finally{btnRetry.Enabled=true;}
    }
    private async Task LoginAsync()
    {
        if(api==null)return;
        btnLogin.Enabled=false;lblError.Text="Signing in...";
        try
        {
            await api.LoginAsync(txtUsername.Text.Trim(),txtPassword.Text);
            lblError.Text="";Hide();
            using(var main=new MainForm(api))main.ShowDialog();
            try{await api.SendAsync("/api/logout","POST");}catch{}
            Show();txtPassword.Clear();
        }
        catch(Exception e){lblError.Text=e.Message;Show();}
        finally{btnLogin.Enabled=true;}
    }
}

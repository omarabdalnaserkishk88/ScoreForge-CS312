using System.ComponentModel;
using System.Data;
using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Text.Json;
using System.Text.Json.Nodes;
using ScoreForge.Desktop.Services;
namespace ScoreForge.Desktop.Forms;
public partial class MainForm : Form
{
    private ApiClient? api;
    private JsonObject[] players=[],games=[],scores=[],ranks=[],rooms=[];
    private JsonObject? round;
    private readonly System.Windows.Forms.Timer poll=new(){Interval=700};
    private readonly System.Windows.Forms.Timer frames=new(){Interval=33};
    private readonly Stopwatch roundWatch=new();
    private bool playBusy, loading;
    private string lastFinished="";
    private Color accent=Color.FromArgb(184,239,118), muted=Color.FromArgb(146,156,174);
    public MainForm(){InitializeComponent();}
    public MainForm(ApiClient client):this()
    {
        api=client;
        lblIdentity.Text=S(api.User,"name")+"\n"+(api.IsAdmin?"Administrator":"Player account");
        lblStatus.Text="Connected · "+api.BaseUrl;
        ConfigureGridStyles(this);
        var navigation=new (Button Button,TabPage Page)[]{(navPlay,pagePlay),(navOverview,pageOverview),(navPlayers,pagePlayers),(navGames,pageGames),(navScores,pageScores),(navLeaderboard,pageLeaderboard),(navAnalytics,pageAnalytics),(navArena,pageArena),(navNetwork,pageNetwork),(navLab,pageLab),(navAudit,pageAudit)};
        foreach(var (button,page) in navigation)button.Click+=async(_,_)=>await RunAsync(async()=>{pages.SelectedTab=page;lblTitle.Text=button.Text;foreach(var item in navigation)item.Button.BackColor=item.Page==page?Color.FromArgb(39,51,34):Color.FromArgb(34,41,54);await RefreshPageAsync();});
        if(!api.IsAdmin)
        {
            foreach(var b in new[]{navPlayers,navLab,navAudit,btnGamesAdd,btnGamesEdit,btnGamesDelete,btnScoresAdd,btnScoresEdit,btnScoresDelete,btnExport,btnReset,btnSessionsRefresh})b.Visible=false;
            pages.TabPages.Remove(pagePlayers);pages.TabPages.Remove(pageLab);pages.TabPages.Remove(pageAudit);
        }
        else
        {
            gameBoard.Visible=false;playSettings.Visible=false;lblHud.Visible=false;lblPlayFeedback.Visible=false;
            gridSessions.Visible=true;btnJoin.Visible=false;btnLeave.Visible=false;
        }
        foreach(var b in new[]{btnOverviewRefresh,btnPlayersRefresh,btnGamesRefresh,btnScoresRefresh,btnLeaderboardRefresh,btnAnalyticsRefresh,btnArenaRefresh,btnAuditRefresh,btnSessionsRefresh})b.Click+=async(_,_)=>await RunAsync(async()=>{await LoadDataAsync();await RefreshPageAsync();});
        searchPlayers.TextChanged+=(_,_)=>BindPlayers();searchGames.TextChanged+=(_,_)=>BindGames();searchScores.TextChanged+=(_,_)=>BindScores();
        gameLeaderboard.SelectedIndexChanged+=(_,_)=>BindRanking();gameAnalytics.SelectedIndexChanged+=(_,_)=>BindRanking();
        foreach(var kind in new[]{"players","games","scores"})
        {
            Button add=kind=="players"?btnPlayersAdd:kind=="games"?btnGamesAdd:btnScoresAdd;
            Button edit=kind=="players"?btnPlayersEdit:kind=="games"?btnGamesEdit:btnScoresEdit;
            Button delete=kind=="players"?btnPlayersDelete:kind=="games"?btnGamesDelete:btnScoresDelete;
            add.Click+=(_,_)=>EditRecord(kind,null);
            edit.Click+=(_,_)=>{var row=Selected(GridFor(kind));if(row!=null)EditRecord(kind,row);};
            delete.Click+=async(_,_)=>await RunAsync(()=>DeleteRecordAsync(kind));
        }
        btnSend.Click+=async(_,_)=>await RunAsync(SendRequestAsync);
        btnRunLab.Click+=async(_,_)=>await RunAsync(RunLabAsync);
        btnJoin.Click+=async(_,_)=>await RunAsync(()=>RoomActionAsync("join"));
        btnLeave.Click+=async(_,_)=>await RunAsync(()=>RoomActionAsync("leave"));
        btnReset.Click+=async(_,_)=>{if(Confirm("Release all arena seats and cancel active rounds?"))await RunAsync(()=>RoomActionAsync("reset"));};
        btnExport.Click+=async(_,_)=>await RunAsync(ExportAsync);
        btnLogout.Click+=(_,_)=>Close();
        btnPassword.Click+=(_,_)=>ChangePassword();
        btnStart.Click+=async(_,_)=>await RunAsync(StartRoundAsync);
        btnStop.Click+=async(_,_)=>{if(Confirm("Stop this round without saving its score?"))await RunAsync(CancelRoundAsync);};
        gameBoard.Paint+=PaintBoard;gameBoard.MouseDown+=async(_,e)=>await RunAsync(()=>ClickTargetAsync(e));
        // Double buffering keeps GDI+ animation smooth; the designer still contains a normal Panel.
        typeof(Panel).GetProperty("DoubleBuffered",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic)?.SetValue(gameBoard,true);
        chartLeaderboard.Paint+=(_,e)=>DrawChart(e.Graphics,chartLeaderboard.ClientRectangle,SelectedRanks(gameLeaderboard),"best");
        chartAnalytics.Paint+=(_,e)=>DrawChart(e.Graphics,chartAnalytics.ClientRectangle,SelectedRanks(gameAnalytics),"average");
        overviewChart.Paint+=(_,e)=>DrawChart(e.Graphics,overviewChart.ClientRectangle,ranks.Where(r=>I(r,"game_id")==games.FirstOrDefault()?["id"]?.GetValue<int>()),"best");
        frames.Tick+=(_,_)=>{if(!IsDisposed&&pages.SelectedTab==pagePlay&&!api.IsAdmin){UpdateHud();gameBoard.Invalidate();}};
        poll.Tick+=async(_,_)=>{if(pages.SelectedTab==pagePlay&&!api.IsAdmin&&!playBusy)await RunAsync(PollRoundAsync,false);};
        Shown+=async(_,_)=>await RunAsync(async()=>{await LoadDataAsync();pages.SelectedTab=api.IsAdmin?pageOverview:pagePlay;await RefreshPageAsync();poll.Start();frames.Start();});
        FormClosed+=(_,_)=>{poll.Stop();frames.Stop();poll.Dispose();frames.Dispose();};
    }
    private async Task RunAsync(Func<Task> work,bool dialog=true)
    {
        try{await work();}
        catch(Exception e)
        {
            if(IsDisposed)return;lblStatus.Text=e.Message;
            if(dialog)MessageBox.Show(this,e.Message,"ScoreForge",MessageBoxButtons.OK,MessageBoxIcon.Warning);
            if(e is ApiFailure{Status:401})Close();
        }
    }
    private static string S(JsonObject? row,string key)=>row?[key]?.ToString()??"";
    private static int I(JsonObject? row,string key)=>int.TryParse(S(row,key),out var n)?n:0;
    private static double D(JsonObject? row,string key)=>double.TryParse(S(row,key),System.Globalization.NumberStyles.Float,System.Globalization.CultureInfo.InvariantCulture,out var n)?n:0;
    private static JsonObject[] Rows(JsonObject data,string key)=>(data[key] as JsonArray)?.OfType<JsonObject>().ToArray()??[];
    private static JsonObject? Selected(DataGridView grid)=>grid.CurrentRow?.Tag as JsonObject;
    private DataGridView GridFor(string kind)=>kind=="players"?gridPlayers:kind=="games"?gridGames:gridScores;
    private bool Confirm(string text)=>MessageBox.Show(this,text,"Confirm",MessageBoxButtons.YesNo,MessageBoxIcon.Question)==DialogResult.Yes;
    private static void ConfigureGridStyles(Control parent)
    {
        foreach(Control c in parent.Controls)
        {
            if(c is DataGridView g)
            {
                g.EnableHeadersVisualStyles=false;g.ColumnHeadersDefaultCellStyle.BackColor=Color.FromArgb(34,41,54);
                g.ColumnHeadersDefaultCellStyle.ForeColor=Color.FromArgb(184,239,118);g.ColumnHeadersHeight=38;
                g.DefaultCellStyle.BackColor=Color.FromArgb(25,30,39);g.DefaultCellStyle.ForeColor=Color.FromArgb(237,240,246);
                g.DefaultCellStyle.SelectionBackColor=Color.FromArgb(49,64,43);g.DefaultCellStyle.SelectionForeColor=Color.White;
                g.GridColor=Color.FromArgb(42,48,60);g.RowTemplate.Height=38;
            }
            ConfigureGridStyles(c);
        }
    }
    private static void Bind(DataGridView grid,IEnumerable<JsonObject> rows,params (string Key,string Label)[] columns)
    {
        grid.Rows.Clear();grid.Columns.Clear();
        foreach(var col in columns)grid.Columns.Add(col.Key,col.Label);
        foreach(var row in rows){int i=grid.Rows.Add(columns.Select(c=>(object)S(row,c.Key)).ToArray());grid.Rows[i].Tag=row;}
    }
    private void FillGames(ComboBox combo)
    {
        string? selected=(combo.SelectedItem as Choice)?.Key;combo.Items.Clear();
        combo.Items.AddRange(games.Select(g=>new Choice(S(g,"id"),S(g,"name"))).ToArray());
        combo.SelectedIndex=Array.FindIndex(games,g=>S(g,"id")==selected);
        if(combo.SelectedIndex<0&&combo.Items.Count>0)combo.SelectedIndex=0;
    }
    private async Task LoadDataAsync()
    {
        if(loading||api==null)return;loading=true;
        try
        {
            var tasks=new[]{"players","games","scores","leaderboard","rooms"}.Select(x=>api.SendAsync("/api/"+x)).ToArray();
            var data=await Task.WhenAll(tasks);if(IsDisposed)return;
            players=Rows(data[0],"players");games=Rows(data[1],"games");scores=Rows(data[2],"scores");ranks=Rows(data[3],"leaderboard");rooms=Rows(data[4],"rooms");
            statPlayers.Text=players.Count(x=>I(x,"active")==1).ToString();statGames.Text=games.Count(x=>I(x,"active")==1).ToString();statScores.Text=scores.Length.ToString();statSeats.Text=(rooms.FirstOrDefault()?["occupied"]?.ToString()??"0")+" / 4";
            FillGames(gameLeaderboard);FillGames(gameAnalytics);BindPlayers();BindGames();BindScores();BindRanking();BindArena();
            Bind(gridRecent,scores.Take(8),("player","Player"),("game","Game"),("points","Score"),("created_at","Recorded"));overviewChart.Invalidate();
            lblStatus.Text="Updated · "+DateTime.Now.ToLongTimeString()+" · "+api.BaseUrl;
        }
        finally{loading=false;}
    }
    private async Task RefreshPageAsync()
    {
        if(api==null)return;
        if(pages.SelectedTab==pagePlay)
        {
            lblTitle.Text=api.IsAdmin?"The arena is alive.":"Reflex Rush.";
            if(api.IsAdmin)Bind(gridSessions,Rows(await api.SendAsync("/api/play/sessions"),"sessions"),("name","Player"),("mode","Difficulty"),("status","Status"),("points","Score"),("hits","Hits"),("misses","Misses"));
            else await PollRoundAsync();
        }
        else if(pages.SelectedTab==pageAudit)Bind(gridAudit,Rows(await api.SendAsync("/api/audit"),"events"),("action","Event"),("actor","Actor"),("detail","Details"),("created_at","Time"));
        else if(pages.SelectedTab==pageArena)await RoomRefreshAsync();
    }
    private void BindPlayers()=>Bind(gridPlayers,players.Where(r=>(S(r,"name")+S(r,"username")).Contains(searchPlayers.Text,StringComparison.OrdinalIgnoreCase)),("id","ID"),("name","Player"),("username","Username"),("active","Active"));
    private void BindGames()=>Bind(gridGames,games.Where(r=>(S(r,"name")+S(r,"genre")).Contains(searchGames.Text,StringComparison.OrdinalIgnoreCase)),("id","ID"),("name","Game"),("genre","Genre"),("max_score","Maximum"),("active","Active"));
    private void BindScores()=>Bind(gridScores,scores.Where(r=>(S(r,"player")+S(r,"game")+S(r,"note")).Contains(searchScores.Text,StringComparison.OrdinalIgnoreCase)),("id","ID"),("player","Player"),("game","Game"),("points","Score"),("note","Note"),("created_at","Recorded"));
    private IEnumerable<JsonObject> SelectedRanks(ComboBox c)=>ranks.Where(r=>S(r,"game_id")==((c.SelectedItem as Choice)?.Key??""));
    private void BindRanking()
    {
        Bind(gridLeaderboard,SelectedRanks(gameLeaderboard),("rank","Rank"),("name","Player"),("best","Best score"),("plays","Plays"));
        Bind(gridAnalytics,SelectedRanks(gameAnalytics),("name","Player"),("best","Best"),("average","Average"),("plays","Plays"));chartLeaderboard.Invalidate();chartAnalytics.Invalidate();
    }
    private void BindArena()
    {
        var room=rooms.FirstOrDefault();lblArenaCount.Text=$"{I(room,"occupied")} / 4 seats occupied";lblPlaySeats.Text=$"{I(room,"occupied")} / 4 seats";
        Bind(gridArena,room==null?[]:Rows(room,"members"),("id","Player ID"),("name","Player"));
    }
    private async Task RoomRefreshAsync(){rooms=Rows(await api!.SendAsync("/api/rooms"),"rooms");if(!IsDisposed)BindArena();}
    private async Task RoomActionAsync(string action)
    {
        var room=rooms.FirstOrDefault()??throw new Exception("No room available.");
        await api!.SendAsync("/api/rooms/"+action,"POST",new{room_id=I(room,"id")});await LoadDataAsync();
    }
    private async Task SendRequestAsync()
    {
        btnSend.Enabled=false;
        try{var r=await api!.RawAsync(txtEndpoint.Text.Trim());lblHttpStatus.Text=$"HTTP {r.Status} · {r.Milliseconds} ms · {api.BaseUrl}";txtResponse.Text=r.Data.ToJsonString(new JsonSerializerOptions{WriteIndented=true});}
        finally{btnSend.Enabled=true;}
    }
    private async Task RunLabAsync()
    {
        btnRunLab.Enabled=false;
        try
        {
            int count=applicants.SelectedIndex==0?3:7;
            var setup=await api!.SendAsync("/api/demo/start","POST");int rid=I(setup,"room_id");
            var ids=(setup["players"] as JsonArray)!.Take(count).Select(n=>n!.GetValue<int>()).ToArray();
            // Each task starts a real HttpClient request. The server serializes only admission.
            var results=await Task.WhenAll(ids.Select(async id=>
            {
                var response=await api.RawAsync("/api/demo/join","POST",new{room_id=rid,player_id=id});
                return new JsonObject{["player_id"]=id,["status"]=response.Status,["message"]=S(response.Data,response.Status==200?"message":"error"),["ms"]=response.Milliseconds};
            }));
            var persisted=Rows(await api.SendAsync("/api/demo/state"),"rooms").FirstOrDefault(x=>I(x,"id")==rid);
            int admitted=results.Count(x=>I(x,"status")==200),rejected=results.Count(x=>I(x,"status")==409);
            bool passed=I(persisted,"occupied")==4&&admitted==3&&rejected==count-3;
            lblLabResult.Text=$"{(passed?"PASSED":"FAILED")} · {I(persisted,"occupied")} / 4 occupied\n{admitted} admitted · {rejected} rejected with HTTP 409";
            Bind(gridLab,results,("player_id","Test player"),("status","HTTP"),("message","Outcome"),("ms","Milliseconds"));
        }
        finally{btnRunLab.Enabled=true;}
    }
    private void EditRecord(string kind,JsonObject? row)
    {
        if(api==null||!api.IsAdmin)return;
        string V(string key,string fallback="")=>row?[key]?.ToString()??fallback;
        Choice[] status=[new("1","Active"),new("0","Disabled / archived")];
        Field[] fields;
        if(kind=="players")fields=row==null?[new("name","Display name"),new("username","Username"),new("password","Initial password (10+ characters)","","password")]:[new("name","Display name",V("name")),new("active","Account status",V("active","1"),"number",status)];
        else if(kind=="games")fields=[new("name","Game name",V("name")),new("genre","Genre",V("genre")),new("max_score","Maximum score",V("max_score","10000"),"number"),new("active","Status",V("active","1"),"number",status)];
        else
        {
            var playerChoices=players.Where(p=>I(p,"active")==1).Select(p=>new Choice(S(p,"id"),S(p,"name"))).ToArray();
            var gameChoices=games.Where(g=>I(g,"active")==1&&(row!=null||S(g,"genre")!="Reaction")).Select(g=>new Choice(S(g,"id"),S(g,"name"))).ToArray();
            if(playerChoices.Length==0||gameChoices.Length==0){MessageBox.Show(this,"Create an active player and eligible game first.");return;}
            fields=[new("player_id","Player",V("player_id"),"number",playerChoices),new("game_id","Game",V("game_id"),"number",gameChoices),new("points","Score",V("points","0"),"number"),new("note","Note",V("note"))];
        }
        using var editor=new EditorForm((row==null?"Add ":"Edit ")+kind,fields,async data=>{await api.SendAsync("/api/"+kind+(row==null?"":"/"+S(row,"id")),row==null?"POST":"PUT",data);await LoadDataAsync();});editor.ShowDialog(this);
    }
    private async Task DeleteRecordAsync(string kind)
    {
        var row=Selected(GridFor(kind));if(row==null)return;
        if(!Confirm("Delete selected record permanently? Linked records may prevent deletion."))return;
        await api!.SendAsync("/api/"+kind+"/"+S(row,"id"),"DELETE");await LoadDataAsync();
    }
    private async Task ExportAsync()
    {
        using var dialog=new SaveFileDialog{Filter="CSV files|*.csv",FileName="ScoreForge_scores.csv"};
        if(dialog.ShowDialog(this)!=DialogResult.OK)return;
        await File.WriteAllBytesAsync(dialog.FileName,await api!.ExportAsync());lblStatus.Text="Scores exported.";
    }
    private void ChangePassword()
    {
        using var editor=new EditorForm("Change password",[new("current","Current password","","password"),new("password","New password (10+ characters)","","password")],async data=>{await api!.SendAsync("/api/password","POST",data);});editor.ShowDialog(this);
    }
    private void DrawChart(Graphics g,Rectangle rect,IEnumerable<JsonObject> data,string key)
    {
        var list=data.Take(8).ToArray();g.Clear(Color.FromArgb(25,30,39));g.SmoothingMode=SmoothingMode.AntiAlias;
        using var font=new Font("Segoe UI",9);using var labelBrush=new SolidBrush(muted);
        if(list.Length==0){g.DrawString("Record scores to see the chart.",font,labelBrush,20,25);return;}
        float max=(float)Math.Max(1,list.Max(x=>D(x,key))),step=(rect.Width-55f)/list.Length;
        for(int i=0;i<list.Length;i++)
        {
            float height=(float)D(list[i],key)/max*(rect.Height-90),x=35+i*step;
            using var brush=new SolidBrush(i==0?accent:Color.FromArgb(181,161,239));
            g.FillRectangle(brush,x,rect.Height-50-height,Math.Max(5,Math.Min(60,step-12)),height);
            g.DrawString(S(list[i],key),font,labelBrush,x,rect.Height-70-height);
            g.DrawString(S(list[i],"name").Split(' ')[0],font,labelBrush,x,rect.Height-34);
        }
    }
    private double Remaining()=>Math.Max(0,D(round,"remaining")-roundWatch.Elapsed.TotalSeconds);
    private bool Active=>S(round,"status")=="active";
    private void SetRound(JsonObject data)
    {
        if(IsDisposed)return;
        round=data["round"] as JsonObject;roundWatch.Restart();
        btnStart.Enabled=!Active;btnStop.Enabled=Active;difficulty.Enabled=!Active;
        if(Active){difficulty.SelectedItem=S(round,"mode");lblPlayFeedback.Text="Tap the glowing target. The server counts your points.";}
        else if(S(round,"status")=="finished")lblPlayFeedback.Text=$"Round complete: {I(round,"points")} points · {I(round,"hits")} hits · best combo {I(round,"best_combo")}\nScore saved automatically. Seat released. View the leaderboard or play again.";
        else if(S(round,"status")=="cancelled")lblPlayFeedback.Text="Round cancelled. No score saved. Your seat is free.";
        UpdateHud();gameBoard.Invalidate();
    }
    private void UpdateHud()
    {
        double time=Active?Remaining():S(round,"status")=="finished"?0:30;
        lblHud.Text=$"{time:0.0}s   |   SCORE {I(round,"points")}   |   COMBO {I(round,"combo")}×   |   ACCURACY {D(round,"accuracy"):0.#}%";
    }
    private async Task PollRoundAsync()
    {
        if(playBusy||api==null)return;playBusy=true;
        try
        {
            SetRound(await api.SendAsync("/api/play/state"));await RoomRefreshAsync();
            if(S(round,"status")=="finished"&&lastFinished!=S(round,"id")){lastFinished=S(round,"id");await LoadDataAsync();}
        }
        finally{playBusy=false;}
    }
    private async Task StartRoundAsync()
    {
        if(playBusy)return;playBusy=true;btnStart.Enabled=false;
        try{SetRound(await api!.SendAsync("/api/play/start","POST",new{mode=difficulty.SelectedItem?.ToString()??"normal"}));await RoomRefreshAsync();}
        finally{playBusy=false;if(!IsDisposed)btnStart.Enabled=!Active;}
    }
    private async Task CancelRoundAsync(){await api!.SendAsync("/api/play/cancel","POST");await PollRoundAsync();}
    private (float X,float Y,float Radius) TargetGeometry()
    {
        var t=round?["target"] as JsonObject;float radius=(float)D(t,"size")/2,margin=radius+12;
        return(margin+(gameBoard.ClientSize.Width-2*margin)*(float)D(t,"x")/1000,margin+(gameBoard.ClientSize.Height-2*margin)*(float)D(t,"y")/1000,radius);
    }
    private void PaintBoard(object? sender,PaintEventArgs e)
    {
        var g=e.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;g.Clear(Color.FromArgb(16,28,33));
        using var gridPen=new Pen(Color.FromArgb(32,50,56));
        for(int x=24;x<gameBoard.Width;x+=36)g.DrawLine(gridPen,x,0,x,gameBoard.Height);
        for(int y=24;y<gameBoard.Height;y+=36)g.DrawLine(gridPen,0,y,gameBoard.Width,y);
        if(!Active||Remaining()<=0)
        {
            using var titleFont=new Font("Segoe UI",28,FontStyle.Bold);using var subFont=new Font("Segoe UI",12);
            using var brush=new SolidBrush(accent);using var gray=new SolidBrush(muted);
            string title=S(round,"status")=="finished"?$"{I(round,"points")} POINTS":"Your reflexes. Your high score.";
            g.DrawString(title,titleFont,brush,new RectangleF(35,140,gameBoard.Width-60,100));g.DrawString("Choose a difficulty and press Start round.",subFont,gray,40,260);return;
        }
        var target=round?["target"] as JsonObject;if(target==null||D(target,"remaining")-roundWatch.Elapsed.TotalSeconds<=0)return;
        var (cx,cy,r)=TargetGeometry();using var fill=new SolidBrush(accent);using var ring=new Pen(Color.FromArgb(181,161,239),3);using var center=new Pen(Color.FromArgb(38,62,44),2);
        g.FillEllipse(fill,cx-r,cy-r,r*2,r*2);g.DrawEllipse(ring,cx-r-6,cy-r-6,r*2+12,r*2+12);
        g.DrawEllipse(center,cx-r*.58f,cy-r*.58f,r*1.16f,r*1.16f);g.DrawLine(center,cx-8,cy,cx+8,cy);g.DrawLine(center,cx,cy-8,cx,cy+8);
    }
    private async Task ClickTargetAsync(MouseEventArgs e)
    {
        if(e.Button!=MouseButtons.Left||playBusy||!Active)return;
        playBusy=true;
        try
        {
            var (x,y,r)=TargetGeometry();bool hit=Math.Pow(e.X-x,2)+Math.Pow(e.Y-y,2)<=r*r;
            var data=await api!.SendAsync("/api/play/"+(hit?"hit":"miss"),"POST",new{round_id=S(round,"id"),target_id=S(round?["target"] as JsonObject,"id")});SetRound(data);
        }
        catch(ApiFailure e2) when(e2.Status is 409 or 429){lblPlayFeedback.Text=e2.Message;}
        finally{playBusy=false;}
    }
}

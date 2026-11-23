namespace ScoreForge.Desktop.Forms;
public partial class EditorForm : Form
{
    public EditorForm(){InitializeComponent();}
    public EditorForm(string title,Field[] fields,Func<Dictionary<string,object>,Task> save):this()
    {
        Text=title;lblHeading.Text=title;
        var inputs=new Dictionary<string,Control>();int y=10;
        foreach(var field in fields)
        {
            var label=new Label{Text=field.Label,Location=new Point(12,y),Size=new Size(410,25),ForeColor=Color.FromArgb(146,156,174)};
            fieldHost.Controls.Add(label);y+=29;
            Control input;
            if(field.Options!=null)
            {
                var combo=new ComboBox{DropDownStyle=ComboBoxStyle.DropDownList};combo.Items.AddRange(field.Options);
                combo.SelectedIndex=Array.FindIndex(field.Options,x=>x.Key==field.Value);
                if(combo.SelectedIndex<0&&combo.Items.Count>0)combo.SelectedIndex=0;input=combo;
            }
            else input=new TextBox{Text=field.Value,UseSystemPasswordChar=field.Kind=="password"};
            input.Location=new Point(12,y);input.Size=new Size(410,32);input.BackColor=Color.FromArgb(16,19,25);input.ForeColor=Color.FromArgb(237,240,246);
            fieldHost.Controls.Add(input);inputs[field.Key]=input;y+=49;
        }
        btnSave.Click+=async(_,_)=>
        {
            btnSave.Enabled=false;lblError.Text="";
            try
            {
                var data=new Dictionary<string,object>();
                foreach(var f in fields)
                {
                    var c=inputs[f.Key];var value=c is ComboBox combo?((Choice?)combo.SelectedItem)?.Key??"":c.Text;
                    if(f.Kind=="number")
                    { if(!int.TryParse(value,out var n))throw new Exception(f.Label+" must be a whole number.");data[f.Key]=n; }
                    else data[f.Key]=value;
                }
                await save(data);DialogResult=DialogResult.OK;Close();
            }
            catch(Exception e){lblError.Text=e.Message;}
            finally{btnSave.Enabled=true;}
        };
    }
}

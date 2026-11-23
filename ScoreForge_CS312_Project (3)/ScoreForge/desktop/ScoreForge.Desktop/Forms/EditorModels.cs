namespace ScoreForge.Desktop.Forms;
public sealed record Choice(string Key,string Label)
{
    public override string ToString()=>Label;
}
public sealed record Field(string Key,string Label,string Value="",string Kind="text",Choice[]? Options=null);

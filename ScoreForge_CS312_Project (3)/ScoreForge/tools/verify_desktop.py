"""Static structure checks only, NOT a C# compiler or a Designer renderer."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
proj=root/'desktop'/'ScoreForge.Desktop'
ET.parse(proj/'ScoreForge.Desktop.csproj')
for name in ['LoginForm','MainForm','EditorForm']:
    logic=(proj/'Forms'/f'{name}.cs').read_text()
    designer=(proj/'Forms'/f'{name}.Designer.cs').read_text()
    assert f'partial class {name}' in logic and f'partial class {name}' in designer
    assert 'InitializeComponent();' in logic and 'void InitializeComponent()' in designer
    declarations=set(re.findall(r'private \w+ (\w+) = null!;',designer))
    creations=set(re.findall(r'^ (\w+) = new \w+\(\);',designer,re.M))
    assert declarations==creations,(name,declarations^creations)
    references=set(re.findall(r'\b((?:btn|lbl|txt|nav|grid|page|chart|stat|search|card|caption)[A-Z]\w*)\b',logic))
    locals_=set(re.findall(r'\bvar\s+(\w+)\s*=',logic))
    assert references<=declarations|locals_,(name,references-declarations-locals_)
    assert not any(x in designer for x in ['HttpClient','WebView','Process.Start','await '])
    # Lexical bracket balance, ignoring strings/comments. This is not type checking.
for p in proj.rglob('*.cs'):
    text=p.read_text()
    cleaned=re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '',text,flags=re.S)
    stack=[];matching={')':'(',']':'[','}':'{'}
    for ch in cleaned:
        if ch in '([{':stack.append(ch)
        elif ch in ')]}':
            assert stack and stack.pop()==matching[ch],p
    assert not stack,p
assert (root/'ScoreForge.Desktop.sln').exists()
assert 'Task.WhenAll' in (proj/'Forms'/'MainForm.cs').read_text()
assert 'HttpClient' in (proj/'Services'/'ApiClient.cs').read_text()
print('PASS: three native designer pairs, control declarations/references, XML, lexical braces, async HTTP and lab wiring.')
print('C# compilation and Windows Designer behavior still require Visual Studio on Windows.')

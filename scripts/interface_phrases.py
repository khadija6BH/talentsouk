from pathlib import Path
import re,json,ast
from html.parser import HTMLParser
root=Path(__file__).resolve().parents[1]
class Texts(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.values=[]
 def handle_starttag(self,t,a):
  if t in ('script','style'):self.skip+=1
  for k,v in a:
   if k in ('placeholder','title','aria-label','alt') and v:self.values.append(v)
 def handle_endtag(self,t):
  if t in ('script','style'):self.skip=max(0,self.skip-1)
 def handle_data(self,d):
  if not self.skip:self.values.append(d)
def interface_phrases():
 values=set()
 for f in (root/'frontend/templates').rglob('*.html'):
  p=Texts();p.feed(re.sub(r'{[#%].*?[%#]}','',f.read_text(encoding='utf-8'),flags=re.S))
  values.update(p.values)
 scripts=[]
 for f in (root/'frontend/templates').rglob('*.html'):
  scripts.extend(re.findall(r'<script[^>]*>(.*?)</script>',f.read_text(encoding='utf-8'),re.S))
 scripts.extend(f.read_text(encoding='utf-8') for f in (root/'frontend/static/js').glob('*.js') if not f.name.startswith('i18n'))
 for s in scripts:
  for m in re.finditer(r'([\"\'`])((?:\\.|(?!\1).)*?)\1',s,re.S):
   value=m[2]
   literal=re.sub(r'\$\{.*?\}|{{.*?}}','',value)
   if not ('<' in literal or '\n' in literal or re.search(r'[{};=]|https?:|/api/|^\.?[/#]',literal)):values.add(value)
  for m in re.finditer(r'>([^<>\n]+)<',s):values.add(m[1])
 for f in (root/'backend').glob('*.py'):
  try:tree=ast.parse(f.read_text(encoding='utf-8'))
  except SyntaxError:continue
  for n in ast.walk(tree):
   if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='error' for t in n.targets) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):values.add(n.value.value)
   if isinstance(n,ast.Call):
    for kw in n.keywords:
     if kw.arg=='page_title' and isinstance(kw.value,ast.Constant) and isinstance(kw.value.value,str):values.add(kw.value.value)
   if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Name) and n.func.id in ('flash','ValueError','AIServiceError')) or (isinstance(n.func,ast.Name) and n.func.id=='jsonify')):
    args=list(n.args)+[kw.value for kw in n.keywords if kw.arg=='error']
    for a in args:
     if isinstance(a,ast.Constant) and isinstance(a.value,str):values.add(a.value)
 result=set()
 for v in values:
  v=re.sub(r'\s+',' ',v).strip()
  literal=re.sub(r'{{.*?}}|\$\{.*?\}','',v)
  if len(literal)<3 or not re.search('[A-Za-z]{3}',literal):continue
  if literal.startswith(('url_for','function','const ','return ','window.')):continue
  if len(literal.split())<2 and not re.match(r'^[A-Z][a-z]+$',literal):continue
  result.add(v)
 return sorted(result)
if __name__=='__main__':
 phrases=interface_phrases()
 (root/'.runtime-logs/interface-phrases.json').write_text(json.dumps(phrases,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Interface phrases:',len(phrases))

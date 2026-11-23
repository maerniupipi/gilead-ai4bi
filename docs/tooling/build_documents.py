from __future__ import annotations
import re,zipfile,shutil
from pathlib import Path
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT

ROOT=Path(__file__).resolve().parents[3]
MD=ROOT/'ReAct/docs/architecture/吉利德AI4BI架构与实施方案.md'
FONT='Heiti SC'


def element(tag,**attrs):
 el=OxmlElement(tag)
 for key,value in attrs.items():el.set(qn(key),str(value))
 return el


def fontify(run,size=None,bold=None,color=None):
 run.font.name=FONT
 props=run._element.get_or_add_rPr()
 fonts=props.find(qn('w:rFonts'))
 if fonts is None:fonts=element('w:rFonts');props.insert(0,fonts)
 for a in ['ascii','hAnsi','eastAsia','cs']:fonts.set(qn('w:'+a),FONT)
 for a in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:
  fonts.attrib.pop(qn('w:'+a),None)
 if size:run.font.size=Pt(size)
 if bold is not None:run.bold=bold
 if color:run.font.color.rgb=RGBColor.from_string(color)


def setup(d,title):
 sec=d.sections[0];sec.page_width=Inches(8.5);sec.page_height=Inches(11)
 sec.left_margin=sec.right_margin=Inches(.8)
 sec.top_margin=Inches(.7);sec.bottom_margin=Inches(.65)
 sec.header_distance=sec.footer_distance=Inches(.3)
 for name in ['Normal','Title','Heading 1','Heading 2','Caption']:
  st=d.styles[name];st.font.name=FONT
  fonts=st.element.get_or_add_rPr().find(qn('w:rFonts'))
  if fonts is None:fonts=element('w:rFonts');st.element.get_or_add_rPr().append(fonts)
  for a in ['ascii','hAnsi','eastAsia','cs']:fonts.set(qn('w:'+a),FONT)
  for a in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:fonts.attrib.pop(qn('w:'+a),None)
  st.font.color.rgb=RGBColor(0,0,0)
  st.paragraph_format.space_after=Pt(7)
  st.paragraph_format.line_spacing=1.22
  props=st.element.get_or_add_pPr();props.append(element('w:snapToGrid',**{'w:val':'0'}))
  border=props.find(qn('w:pBdr'))
  if border is not None:props.remove(border)
 d.styles['Normal'].font.size=Pt(11)
 d.styles['Title'].font.size=Pt(23);d.styles['Title'].font.bold=True
 d.styles['Title'].paragraph_format.space_after=Pt(16)
 d.styles['Heading 1'].font.size=Pt(16);d.styles['Heading 1'].font.bold=True
 d.styles['Heading 1'].paragraph_format.space_after=Pt(12)
 d.styles['Heading 2'].font.size=Pt(12);d.styles['Heading 2'].font.bold=True
 d.styles['Caption'].font.size=Pt(9);d.styles['Caption'].font.color.rgb=RGBColor.from_string('596775')
 f=sec.footer.paragraphs[0];f.alignment=WD_ALIGN_PARAGRAPH.RIGHT
 r=f.add_run();fontify(r,9,color='666666')
 r._r.append(element('w:fldChar',**{'w:fldCharType':'begin'}))
 instr=element('w:instrText');instr.text=' PAGE ';r._r.append(instr)
 r._r.append(element('w:fldChar',**{'w:fldCharType':'end'}))
 d.core_properties.title=title;d.core_properties.subject='吉利德 AI4BI POC 设计与实施'
 d.core_properties.author='';d.core_properties.last_modified_by=''


def inline(p,s,size=None):
 # Preserve labels and business text; inline code is styled, not executed.
 for part in re.split(r'(`[^`]+`|\*\*[^*]+\*\*)',s):
  if not part:continue
  code=part.startswith('`');bold=part.startswith('**')
  v=part[1:-1] if code else part[2:-2] if bold else part
  v=re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',v)
  run=p.add_run(v);fontify(run,9.5 if code else size,bold=bold or None)


def make_table(d,lines):
 data=[[x.strip() for x in line.strip().strip('|').split('|')] for line in lines]
 data=[row for row in data if not all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in row)]
 n=len(data[0]);t=d.add_table(rows=0,cols=n);t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
 widths={2:[1.6,5.3],3:[1.85,2.65,2.4],4:[1.5,1.65,1.65,2.1]}[n]
 if data[0][0]=='表名':widths=[2.15,.5,.85,3.4]
 if data[0][0]=='场景':widths=[2.3,1.75,1.75,1.1]
 for col,w in zip(t.columns,widths):col.width=Inches(w)
 props=t._tbl.tblPr
 props.append(element('w:tblLayout',**{'w:type':'fixed'}))
 borders=element('w:tblBorders')
 for edge in ['top','left','bottom','right','insideH','insideV']:
  borders.append(element('w:'+edge,**{'w:val':'single','w:sz':'4','w:color':'D5DBE1'}))
 props.append(borders)
 margins=element('w:tblCellMar')
 for side in ['top','bottom','left','right']:margins.append(element('w:'+side,**{'w:w':'80','w:type':'dxa'}))
 props.append(margins)
 for i,row in enumerate(data):
  cells=t.add_row().cells
  trp=t.rows[-1]._tr.get_or_add_trPr();trp.append(element('w:cantSplit'))
  if i==0:trp.append(element('w:tblHeader'))
  for j,(c,txt) in enumerate(zip(cells,row)):
   c.width=Inches(widths[j]);c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   c._tc.get_or_add_tcPr().append(element('w:shd',**{'w:fill':'263A4D' if i==0 else 'F5F7F9' if i%2==0 else 'FFFFFF'}))
   p=c.paragraphs[0];p.paragraph_format.space_after=Pt(1);p.paragraph_format.space_before=Pt(1)
   p.paragraph_format.line_spacing=1.16
   inline(p,txt,9.5 if n>2 else 10)
   for r in p.runs:
    if i==0:fontify(r,10,bold=True,color='FFFFFF')
  # no forced row heights: text wraps naturally.
 d.add_paragraph().paragraph_format.space_after=Pt(0)


def build_main():
 d=Document();setup(d,'吉利德 AI4BI POC 架构与实施方案')
 lines=MD.read_text().splitlines();i=0;new_page=False
 while i<len(lines):
  line=lines[i].strip()
  if not line:i+=1;continue
  if line=='<!-- page -->':new_page=True;i+=1;continue
  if line.startswith('<!--'):i+=1;continue
  if line.startswith('|'):
   rows=[]
   while i<len(lines) and lines[i].strip().startswith('|'):rows.append(lines[i]);i+=1
   make_table(d,rows);continue
  if line.startswith('```'):
   i+=1
   while i<len(lines) and not lines[i].startswith('```'):
    p=d.add_paragraph();p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.05
    r=p.add_run(lines[i]);fontify(r,9.5)
    p.paragraph_format.left_indent=Inches(.2);i+=1
   i+=1;d.add_paragraph();continue
  image=re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',line)
  if image:
   path=(MD.parent/image.group(2)).resolve()
   p=d.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
   p.paragraph_format.space_after=Pt(4)
   pic=p.add_run().add_picture(str(path),width=Inches(6.85))
   pic._inline.docPr.set('descr',image.group(1))
   cap=d.add_paragraph(image.group(1),'Caption');cap.alignment=WD_ALIGN_PARAGRAPH.CENTER
   i+=1;continue
  if line.startswith('# '):p=d.add_paragraph(style='Title');inline(p,line[2:]);i+=1;continue
  if line.startswith('## '):
   p=d.add_paragraph(style='Heading 1');p.paragraph_format.page_break_before=new_page;new_page=False;inline(p,line[3:]);i+=1;continue
  p=d.add_paragraph();inline(p,line)
  i+=1
 out=ROOT/'吉利德AI4BI_POC架构与实施方案.docx';d.save(out);print(out)


def build_supplement():
 d=Document();setup(d,'吉利德 AI4BI 项目补充材料')
 d.add_paragraph('吉利德 AI4BI 项目补充材料','Title')
 d.add_paragraph('DDI 标准报表供参考。系统应能控制哪些用户可以访问该报表，并按销售区域控制数据访问权限。')
 source=ROOT/'资料/Gilead AI4BI Project Supplementary Material.docx'
 with zipfile.ZipFile(source) as z:
  names=[n for n in z.namelist() if n.startswith('word/media/') and n.endswith('.png')]
  if names:
   import io
   img=io.BytesIO(z.read(names[0]))
   p=d.add_paragraph();p.add_run().add_picture(img,width=Inches(6.85))
   d.add_paragraph('原始标准报表参考图','Caption')
 d.add_paragraph('DDI 数据的关键绩效指标 包括但不限于以下指标','Heading 1')
 for text in ['达成率','指标（数量、金额）','销售数量','销售金额','同比增长（季度累计、年度累计、月度）','环比增长（上个季度）']:
  d.add_paragraph(text,style='List Bullet')
 for p in d.paragraphs:
  for r in p.runs:fontify(r)
 out=ROOT/'Gilead AI4BI Project Supplementary Material_中文.docx';d.save(out);print(out)

if __name__=='__main__':build_main();build_supplement()

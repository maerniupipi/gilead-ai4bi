from pathlib import Path
from html import escape

OUT=Path(__file__).resolve().parents[1]/'diagrams'
FONT='Heiti SC, PingFang SC, sans-serif'

def svg_start(w,h):
 return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="#465a70"/></marker></defs><rect width="100%" height="100%" fill="white"/>']

def text(x,y,content,size=25,color='#142a40',anchor='middle',bold=False):
 return f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{color}" text-anchor="{anchor}"'+(' font-weight="600"' if bold else '')+'>'+escape(content)+'</text>'

def box(x,y,w,h,lines,planned=False):
 fill='#f5f6f8' if planned else '#edf4fa';stroke='#8b97a5' if planned else '#355675'
 result=[f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"'+(' stroke-dasharray="7 5"' if planned else '')+'/>']
 top=y+h/2-(len(lines)-1)*17+8
 for i,line in enumerate(lines):result.append(text(x+w/2,top+i*34,line,25 if i else 27,bold=i==0))
 return ''.join(result)

def arrow(points,label=None,lx=None,ly=None,dashed=False):
 a=f'<path d="{points}" fill="none" stroke="#465a70" stroke-width="2.5" marker-end="url(#a)"'+(' stroke-dasharray="7 5"' if dashed else '')+'/>'
 if label:a+=text(lx,ly,label,22)
 return a

s=svg_start(1200,880)
s.append(text(40,35,'实线 现有基础或本次适配     虚线 待实施或待发布',22,anchor='start'))
s.extend([box(40,70,250,100,['网页端','Vue 3 已有']),box(40,240,250,110,['Okta 企业微信','待接入'],True),box(360,70,450,130,['FastAPI 与 Agent Loop','会话 任务 编排 证据呈现']),box(900,70,260,130,['独立控制库','gilead_agent_loop']),box(360,270,450,110,['原生实验中心适配','SSE 与同次 trace 校验']),box(40,440,250,110,['协调模型','沿用兼容配置']),box(360,470,450,170,['强生实验中心','知识检索 SQL生成 执行','既有模型管理']),box(900,300,260,110,['吉利德授权策略','待实现'],True),box(900,490,260,110,['吉利德知识与实验室','待发布'],True),box(40,650,250,110,['标准报表 模板导出','待完善'],True),box(360,760,450,90,['独立模拟业务库 gilead_poc','六表数据 使用只读账号'])])
s.extend([arrow('M290 120 H355'),arrow('M290 290 H330 V175 H355',dashed=True),arrow('M810 135 H895'),arrow('M585 200 V265'),arrow('M360 160 H315 V495 H295'),arrow('M585 380 V465'),arrow('M900 355 H855 V510 H815',dashed=True),arrow('M900 545 H815',dashed=True),arrow('M585 640 V755','数据源18',650,700),arrow('M360 180 H310 V705 H295',dashed=True)])
s.append('</svg>');(OUT/'01-总体架构.svg').write_text(''.join(s))

s=svg_start(1200,1040)
xs=[90,345,600,855,1110];names=['业务用户','ReAct','原生适配器','强生实验中心','吉利德库']
for x,n in zip(xs,names):
 s.append(box(x-83,22,166,70,[n]));s.append(f'<path d="M{x} 92 V1010" stroke="#b9c5d0" stroke-dasharray="6 5" stroke-width="2"/>')
steps=[(0,1,'问题与会话',150),(1,1,'口径检索与拆解',215),(1,2,'ask_lab actual',290),(2,3,'POST 原生接口',360),(3,3,'知识 SQL 授权编译',430),(3,4,'只读 SQL',500),(4,3,'查询结果',560),(3,2,'SSE trace_id done',620),(2,3,'GET 同一 trace',680),(3,2,'步骤16 SQL与行',740),(2,1,'校验后保存证据',800),(1,2,'query_db 相同SQL',860),(2,1,'已执行结果',920),(1,0,'回答与来源',980)]
for a,b,l,y in steps:
 if a==b:
  x=xs[a];s.append(arrow(f'M{x} {y-20} H{x+125} V{y+10} H{x}',l,x+100,y-30))
 else:
  s.append(arrow(f'M{xs[a]} {y} H{xs[b]}',l,(xs[a]+xs[b])/2,y-13))
s.insert(2,text(600,125,'可信身份与吉利德授权闭环待实现  实验室待发布',22,color='#6e3540'))
s.append('</svg>');(OUT/'02-问答链路.svg').write_text(''.join(s))

s=svg_start(1200,960)
s.append(text(40,35,'实线 已有基础与执行步骤     虚线 后续实验室开通',22,anchor='start'))
s.extend([box(40,70,520,100,['中文六表数据字典','133列 保留类型空值语义']),box(640,70,520,100,['确定性合成模拟数据','跨年 零目标 退货 调区等测试']),box(40,240,520,100,['生成 MySQL DDL','build_schema 与结构清单']),box(640,240,520,100,['小批次事务与进度标记','中断后核对进度继续装载']),box(340,420,520,100,['新建业务库 gilead_poc','同一阿里云实例 独立账号']),box(40,590,390,100,['只读核验','结构 关联 KPI 权限']),box(520,590,640,100,['实验中心数据源18','已注册 连接测试成功']),box(30,800,260,100,['吉利德知识库','六表 字典 KPI SQL'],True),box(330,800,260,100,['发布 DDI 实验室','取得 API调用ID'],True),box(630,800,260,100,['ReAct 绑定 actual','原生接口配置'],True),box(930,800,240,100,['真实业务验收','KPI 与区域权限'],True)])
s.extend([arrow('M300 170 V235'),arrow('M900 170 V235'),arrow('M300 340 V380 H500 V415'),arrow('M900 340 V380 H700 V415'),arrow('M465 520 V555 H235 V585'),arrow('M735 520 V585'),arrow('M840 690 V745 H160 V795',dashed=True),arrow('M290 850 H325',dashed=True),arrow('M590 850 H625',dashed=True),arrow('M890 850 H925',dashed=True)])
s.append(text(600,940,'既有强生代码与真实业务数据不作修改',23,color='#596775'))
s.append('</svg>');(OUT/'03-数据与实验室开通.svg').write_text(''.join(s))

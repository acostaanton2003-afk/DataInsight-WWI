import type { EChartsCoreOption } from 'echarts/core';
import type { Month } from '../lib/api';
import { axisAmount, formatAmount, formatCount, monthLabel } from '../lib/format';
interface Point { dataIndex:number }
function index(value: unknown): number {
  const item = (Array.isArray(value) ? value[0] : value) as Point | undefined;
  return item?.dataIndex ?? 0;
}
const base = {
  animationDuration:400, textStyle:{fontFamily:'system-ui, sans-serif', color:'#6a7a80'},
  aria:{enabled:true},
};
export function monthlyOption(rows: Month[]): EChartsCoreOption {
  return {...base,
    grid:{left:60,right:22,top:30,bottom:40},
    tooltip:{trigger:'axis',renderMode:'richText',confine:true,backgroundColor:'#132b32',borderWidth:0,textStyle:{color:'#fff'},
      formatter:(value:unknown) => {const row=rows[index(value)]; return row ? `${monthLabel(row.anio,row.mes)}\nVentas: ${formatAmount(row.importe)}\nFacturas: ${formatCount(row.cantidad_facturas)}` : ''; }},
    xAxis:{type:'category',boundaryGap:false,data:rows.map(row=>monthLabel(row.anio,row.mes)),
      axisLine:{lineStyle:{color:'#dfe7e7'}},axisTick:{show:false},axisLabel:{fontSize:11,hideOverlap:true}},
    yAxis:{type:'value',axisLabel:{formatter:axisAmount,fontSize:11},splitLine:{lineStyle:{color:'#edf1f1',type:'dashed'}}},
    series:[{type:'line',name:'Ventas sin impuestos',data:rows.map(row=>Number(row.importe)),
      smooth:0.18,showSymbol:false,symbolSize:7,lineStyle:{width:3,color:'#168a80'},itemStyle:{color:'#168a80'},
      areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(22,138,128,.22)'},{offset:1,color:'rgba(22,138,128,.01)'}]}}}],
  };
}
export interface RankRow { key:number; id:number|null; name:string; amount:string }
export function rankingOption(rows:RankRow[], color:string): EChartsCoreOption {
  return {...base,
    grid:{left:12,right:60,top:12,bottom:28,
      outerBounds:{left:12,right:60,top:12,bottom:28},outerBoundsContain:'axisLabel'},
    tooltip:{trigger:'axis',renderMode:'richText',confine:true,backgroundColor:'#132b32',borderWidth:0,textStyle:{color:'#fff',fontSize:11,width:250,overflow:'break'},
      formatter:(value:unknown) => {const row=rows[index(value)];return row ? `${row.name}\nID: ${row.id ?? 'Desconocido'}\nVentas: ${formatAmount(row.amount)}` : ''; }},
    xAxis:{type:'value',axisLabel:{formatter:axisAmount,fontSize:10},splitLine:{lineStyle:{color:'#edf1f1',type:'dashed'}}},
    yAxis:{type:'category',inverse:true,data:rows.map((row,i)=>`${String(i+1).padStart(2,'0')}  ${row.name}`),
      axisLine:{show:false},axisTick:{show:false},axisLabel:{width:180,height:28,overflow:'break',lineOverflow:'truncate',lineHeight:13,fontSize:11,color:'#465d65'}},
    series:[{type:'bar',data:rows.map(row=>Number(row.amount)),barMaxWidth:13,
      itemStyle:{color,borderRadius:[0,4,4,0]},label:{show:true,position:'right',formatter:(value:unknown)=>axisAmount(Number(rows[index(value)]?.amount ?? 0)),fontSize:10,color:'#536a72'}}],
    // ECharts vuelve a aplicar esta variante al redimensionar el contenedor.
    media:[{query:{maxWidth:460},option:{
      grid:{right:48,outerBounds:{left:12,right:48,top:12,bottom:28}},
      yAxis:{axisLabel:{width:130,height:28,fontSize:10,lineHeight:13}},
    }},{option:{
      grid:{right:60,outerBounds:{left:12,right:60,top:12,bottom:28}},
      yAxis:{axisLabel:{width:180,height:28,fontSize:11,lineHeight:13}},
    }}],
  };
}

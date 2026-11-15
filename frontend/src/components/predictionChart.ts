import type {EChartsCoreOption} from 'echarts/core';
import type {Month} from '../lib/api';
import {cents,type Predictions} from '../lib/predictions';
import {axisAmount,formatAmount,monthLabel} from '../lib/format';
export function predictionOption(history:Month[],prediction:Predictions):EChartsCoreOption {
  const future=prediction.forecasts;const n=history.length;
  const labels=[...history.map(r=>monthLabel(r.anio,r.mes)),...future.map(r=>{const [y,m]=r.month.split('-').map(Number);return monthLabel(y,m);})];
  return {animationDuration:300,aria:{enabled:true},textStyle:{fontFamily:'system-ui,sans-serif',color:'#6a7a80'},
    grid:{left:60,right:22,top:28,bottom:40,outerBounds:{left:8,right:16,top:8,bottom:8}},
    tooltip:{trigger:'axis',renderMode:'richText',confine:true,backgroundColor:'#132b32',borderWidth:0,textStyle:{color:'#fff',fontSize:11},
      formatter:(raw:unknown)=>{
        const item=(Array.isArray(raw)?raw[0]:raw) as {dataIndex?:number}|undefined;const i=item?.dataIndex??0;
        if(i<n) return `${labels[i]}\nReal: ${formatAmount(history[i].importe)}`;
        const point=future[i-n];return point ? `${labels[i]}\nEstimado: ${formatAmount(point.forecast)}\nBanda descriptiva: ${formatAmount(point.lower)} — ${formatAmount(point.upper)}`:'';
      }},
    xAxis:{type:'category',boundaryGap:false,data:labels,axisLine:{lineStyle:{color:'#dfe7e7'}},axisTick:{show:false},axisLabel:{hideOverlap:true,fontSize:11}},
    yAxis:{type:'value',axisLabel:{formatter:axisAmount,fontSize:11},splitLine:{lineStyle:{color:'#edf1f1',type:'dashed'}}},
    series:[
      {name:'Límite inferior',type:'line',stack:'banda',stackStrategy:'all',symbol:'none',silent:true,lineStyle:{opacity:0},itemStyle:{opacity:0},
        data:[...Array(n).fill(null),...future.map(r=>Number(r.lower))]},
      {name:'Banda descriptiva',type:'line',stack:'banda',stackStrategy:'all',symbol:'none',silent:true,lineStyle:{opacity:0},areaStyle:{color:'rgba(203,145,54,.22)'},
        data:[...Array(n).fill(null),...future.map(r=>Number(cents(r.upper)-cents(r.lower))/100)]},
      {name:'Ventas reales',type:'line',showSymbol:false,lineStyle:{color:'#168a80',width:2.5},itemStyle:{color:'#168a80'},
        data:[...history.map(r=>Number(r.importe)),null,null,null],z:3},
      {name:'Pronóstico experimental',type:'line',symbol:'circle',symbolSize:6,lineStyle:{color:'#c58b33',width:2.5,type:'dashed'},itemStyle:{color:'#c58b33'},
        data:[...Array(Math.max(0,n-1)).fill(null),Number(history[n-1].importe),...future.map(r=>Number(r.forecast))],z:4},
    ]};
}

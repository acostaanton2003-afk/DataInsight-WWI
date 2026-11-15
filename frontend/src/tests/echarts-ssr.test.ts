// @vitest-environment node
import {it,expect,vi} from 'vitest';
import {init,use} from 'echarts/core';
import {LineChart,BarChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,AriaComponent} from 'echarts/components';
import {SVGRenderer} from 'echarts/renderers';
import {monthlyOption,rankingOption} from '../components/charts';
import {predictionOption} from '../components/predictionChart';
import {parsePredictions} from '../lib/predictions';
import {predictions,months} from './fixtures';
use([LineChart,BarChart,GridComponent,TooltipComponent,AriaComponent,SVGRenderer]);
it('ECharts real genera SVG mensual y de ranking sin navegador',()=>{
  const options=[monthlyOption([{anio:2013,mes:1,importe:'30.00',cantidad_facturas:2},{anio:2013,mes:2,importe:'40.00',cantidad_facturas:3}]),
    rankingOption([{key:1,id:7,name:'Producto ficticio',amount:'30.00'}],'#168a80')];
  for(const option of options){
    const chart=init(null,undefined,{renderer:'svg',ssr:true,width:700,height:320});
    try {chart.setOption({...option,animation:false});const svg=chart.renderToSVGString();
      expect(svg).toContain('<svg');expect(svg).toContain('<path');expect(svg).not.toContain('NaN');
    } finally {chart.dispose();}
  }
});

it('ranking adaptable: etiquetas en dos líneas, grid válido y sin aviso legado',()=>{
  const warn=vi.spyOn(console,'warn').mockImplementation(()=>{});
  const error=vi.spyOn(console,'error').mockImplementation(()=>{});
  const rows=Array.from({length:10},(_,i)=>({key:i+1,id:i+1,
    name:`Producto ficticio con nombre largo y variante ${i+1}`,amount:`${1000-i}.00`}));
  // Anchos interiores correspondientes a 375/493 px y tarjeta de escritorio.
  for(const width of [341,451,534]) {
    const chart=init(null,undefined,{renderer:'svg',ssr:true,width,height:410});
    try {
      chart.setOption({...rankingOption(rows,'#168a80'),animation:false});
      const option=chart.getOption() as {grid:{outerBounds:object;containLabel?:boolean}[];yAxis:{axisLabel:{width:number;overflow:string}}[]};
      expect(option.grid[0].containLabel).not.toBe(true);
      expect(option.grid[0].outerBounds).toBeTruthy();
      expect(option.yAxis[0].axisLabel.width).toBe(width<=460?130:180);
      expect(option.yAxis[0].axisLabel.overflow).toBe('break');
      const svg=chart.renderToSVGString();expect(svg).not.toContain('NaN');
      expect(svg).toContain('Producto');
      // La variante móvil no debe quedarse aplicada al volver a escritorio.
      chart.resize({width:700,height:365});
      expect((chart.getOption() as typeof option).yAxis[0].axisLabel.width).toBe(180);
    } finally {chart.dispose();}
  }
  expect([...warn.mock.calls,...error.mock.calls].flat().join(' ')).not.toMatch(/containLabel|useLegacyGridContainLabel/);
});

it('gráfico de predicciones real genera SVG con históricos y bandas sin NaN',()=>{
  const chart=init(null,undefined,{renderer:'svg',ssr:true,width:341,height:320});
  try{chart.setOption({...predictionOption(months,parsePredictions(predictions)),animation:false});
    const svg=chart.renderToSVGString();expect(svg).toContain('<path');expect(svg).not.toContain('NaN');
  }finally{chart.dispose();}
});

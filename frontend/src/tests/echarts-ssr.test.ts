// @vitest-environment node
import {it,expect} from 'vitest';
import {init,use} from 'echarts/core';
import {LineChart,BarChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,AriaComponent} from 'echarts/components';
import {SVGRenderer} from 'echarts/renderers';
import {monthlyOption,rankingOption} from '../components/charts';
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

import {it,expect,vi} from 'vitest';
import {render} from '@testing-library/react';
import {Chart} from '../components/Chart';
const mocks=vi.hoisted(()=>({setOption:vi.fn(),resize:vi.fn(),dispose:vi.fn(),init:vi.fn(),use:vi.fn()}));
vi.mock('echarts/core',()=>({init:mocks.init,use:mocks.use}));
vi.mock('echarts/charts',()=>({LineChart:{},BarChart:{}}));
vi.mock('echarts/components',()=>({GridComponent:{},TooltipComponent:{},AriaComponent:{}}));
vi.mock('echarts/renderers',()=>({SVGRenderer:{}}));
it('crea SVG, redimensiona y libera el gráfico y observador',()=>{
  mocks.init.mockReturnValue(mocks);
  let callback:()=>void=()=>{};
  const observe=vi.fn(),disconnect=vi.fn();
  class Observer {constructor(fn:()=>void){callback=fn;}observe=observe;disconnect=disconnect;}
  vi.stubGlobal('ResizeObserver',Observer);
  const {unmount}=render(<Chart option={{animation:false}} label="Prueba"/>);
  expect(mocks.init.mock.calls[0][2]).toEqual({renderer:'svg'});
  expect(mocks.setOption).toHaveBeenCalledWith({animation:false});
  callback();expect(mocks.resize).toHaveBeenCalledOnce();
  unmount();expect(mocks.dispose).toHaveBeenCalledOnce();expect(disconnect).toHaveBeenCalledOnce();
});

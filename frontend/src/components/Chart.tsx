import { useEffect, useRef } from 'react';
import { init, use, type EChartsCoreOption } from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, AriaComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
use([LineChart, BarChart, GridComponent, TooltipComponent, AriaComponent, SVGRenderer]);
export function Chart({option, label, className=''}: {option:EChartsCoreOption; label:string; className?:string}) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const chart = init(container.current, undefined, {renderer:'svg'});
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    return () => {observer.disconnect(); chart.dispose();};
  }, [option]);
  return <div ref={container} className={`chart ${className}`} role="img" aria-label={label}/>;
}

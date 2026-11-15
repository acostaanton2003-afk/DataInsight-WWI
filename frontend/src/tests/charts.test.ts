import {it,expect} from 'vitest';
import {monthlyOption,rankingOption} from '../components/charts';
import {months} from './fixtures';
it('tooltip mensual usa cadena exacta y conteo de API',()=>{
  const option=monthlyOption(months);
  const tooltip=option.tooltip as {formatter:(value:unknown)=>string;renderMode:string};
  expect(tooltip.renderMode).toBe('richText');
  expect(tooltip.formatter([{dataIndex:0}])).toContain('30,00');
  expect(tooltip.formatter([{dataIndex:0}])).toContain('Facturas: 2');
});
it('tooltip de ranking conserva precisión y nombre como texto',()=>{
  const rows=[{key:1,id:7,name:'<script>ficticio</script>',amount:'9007199254740993.01'}];
  const option=rankingOption(rows,'#168a80');
  const tooltip=option.tooltip as {formatter:(value:unknown)=>string;renderMode:string};
  expect(tooltip.renderMode).toBe('richText');
  expect(tooltip.formatter([{dataIndex:0}])).toContain('9.007.199.254.740.993,01');
  expect(tooltip.formatter([{dataIndex:0}])).toContain(rows[0].name);
});

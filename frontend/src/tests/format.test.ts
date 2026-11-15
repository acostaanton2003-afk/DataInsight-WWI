import { describe, it, expect } from 'vitest';
import {formatAmount,formatCount,monthLabel} from '../lib/format';
describe('formato exacto',()=>{
  it.each([['0.00','0,00'],['172261341.20','172.261.341,20'],['9007199254740993.01','9.007.199.254.740.993,01'],['-12.30','−12,30']])('formatea %s sin float',(value,expected)=>expect(formatAmount(value)).toBe(expected));
  it.each(['1.1','NaN','1e3','Infinity','', '1,23'])('rechaza %s',value=>expect(()=>formatAmount(value)).toThrow());
  it('formatea conteos y mes sin zona horaria local',()=>{
    expect(formatCount(70510)).toBe('70.510');
    expect(monthLabel(2013,1)).toContain('2013');
    expect(monthLabel(null,null)).toBe('Sin fecha');
  });
});

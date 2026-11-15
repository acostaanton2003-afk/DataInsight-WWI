import {amount,count,object,text,type Parser,type Month} from './api';
export interface ForecastPoint {month:string;forecast:string;lower:string;upper:string;historical_abs_error_p90:string}
export interface PredictionCoverage {
  observed_months:number;usable_months:number;observed_first:string;observed_last:string;complete_through:string;excluded_months:string[];
  final_first_invoice_date:string;final_last_invoice_date:string;final_days_with_sales:number;
}
export interface Predictions {
  selected_model:'naive'|'moving_average_3'|'ridge';metric:'ventas_sin_impuestos';currency:null;
  backtesting:{mae:string;rmse:string;smape:string};coverage:PredictionCoverage;
  forecasts:ForecastPoint[];completeness_verified:false;
  uncertainty:{method:string;samples_per_horizon:number};
}
const invalid=():never=>{throw new Error('Predicciones incompatibles.');};
export function monthOrdinal(value:string) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return invalid();
  const [year,month]=value.split('-').map(Number);
  if(year<1)return invalid();return year*12+month-1;
}
export function cents(value:string) {return BigInt(amount(value).replace('.',''));}
const metric=(value:unknown)=>typeof value==='string' && /^\d+(?:\.\d+)?$/.test(value) ? value:invalid();
const month=(value:unknown)=>{const result=text(value);monthOrdinal(result);return result;};
export const parsePredictions:Parser<Predictions>=value=>{
  const row=object(value);const cover=object(row.coverage),backtesting=object(row.backtesting),uncertainty=object(row.uncertainty);
  const name=text(row.selected_model);
  if(!['naive','moving_average_3','ridge'].includes(name) || row.metric!=='ventas_sin_impuestos' || row.currency!==null || row.completeness_verified!==false)return invalid();
  if(!Array.isArray(row.forecasts)||row.forecasts.length!==3||!Array.isArray(cover.excluded_months))return invalid();
  const coverage:PredictionCoverage={observed_months:count(cover.observed_months),usable_months:count(cover.usable_months),
    observed_first:month(cover.observed_first),observed_last:month(cover.observed_last),complete_through:month(cover.complete_through),
    excluded_months:cover.excluded_months.map(month),final_first_invoice_date:text(cover.final_first_invoice_date),
    final_last_invoice_date:text(cover.final_last_invoice_date),final_days_with_sales:count(cover.final_days_with_sales)};
  const first=monthOrdinal(coverage.observed_first),last=monthOrdinal(coverage.observed_last),cutoff=monthOrdinal(coverage.complete_through);
  if(last-first+1!==coverage.observed_months || cutoff-first+1!==coverage.usable_months || cutoff>last || cutoff<first)return invalid();
  if(coverage.excluded_months.length!==last-cutoff || coverage.excluded_months.some((m,i)=>monthOrdinal(m)!==cutoff+i+1))return invalid();
  const forecasts=row.forecasts.map((item,i)=>{
    const point=object(item);const result:ForecastPoint={month:month(point.month),forecast:amount(point.forecast),
      lower:amount(point.lower),upper:amount(point.upper),historical_abs_error_p90:amount(point.historical_abs_error_p90)};
    if(monthOrdinal(result.month)!==cutoff+i+1 || cents(result.lower)>cents(result.forecast) || cents(result.upper)<cents(result.forecast) || cents(result.historical_abs_error_p90)<0n)return invalid();
    return result;
  });
  const smape=metric(backtesting.smape);if(Number(smape)>200)return invalid();
  return {selected_model:name as Predictions['selected_model'],metric:'ventas_sin_impuestos',currency:null,
    backtesting:{mae:metric(backtesting.mae),rmse:metric(backtesting.rmse),smape},coverage,forecasts,completeness_verified:false,
    uncertainty:{method:text(uncertainty.method),samples_per_horizon:count(uncertainty.samples_per_horizon)}};
};
export function compatibleHistory(history:Month[],prediction:Predictions) {
  const coverage=prediction.coverage;const first=monthOrdinal(coverage.observed_first);
  if(history.length!==coverage.observed_months || prediction.metric!=='ventas_sin_impuestos' || prediction.currency!==null)return invalid();
  history.forEach((row,i)=>{
    if(row.anio===null||row.mes===null || row.anio*12+row.mes-1!==first+i)return invalid();
    amount(row.importe);
  });
  return history.slice(0,coverage.usable_months);
}

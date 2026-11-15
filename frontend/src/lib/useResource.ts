import { useEffect, useState } from 'react';
import { fetchApi, type Parser } from './api';
import {errorMessage} from './http';
export type Resource<T> = { status:'loading' } | { status:'error'; message?:string } | { status:'success'; data:T; updated:Date };
export function useResource<T>(path: string, parse: Parser<T>, refresh: number, enabled = true) {
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<Resource<T>>({status:'loading'});
  useEffect(() => {
    if (!enabled) {setState({status:'loading'});return;}
    const controller = new AbortController(); let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 25000);
    setState({status:'loading'});
    fetchApi(path, parse, controller.signal).then(data => {
      if (active) setState({status:'success', data, updated:new Date()});
    }).catch(error => { if (active) setState({status:'error',message:errorMessage(error)}); })
      .finally(() => window.clearTimeout(timeout));
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [path, parse, refresh, retry, enabled]);
  return {state, reload: () => setRetry(value => value + 1)};
}

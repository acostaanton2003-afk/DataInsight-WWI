import type { ReactNode } from 'react';
import type { Resource } from '../lib/useResource';
import { SectionState } from './SectionState';
export function ResourceView<T>({state, retry, isEmpty, children}: {
  state:Resource<T>; retry:()=>void; isEmpty?:(data:T)=>boolean; children:(data:T)=>ReactNode;
}) {
  if (state.status !== 'success') return <SectionState kind={state.status} retry={retry}/>;
  if (isEmpty?.(state.data)) return <SectionState kind="empty"/>;
  return children(state.data);
}

import {describe,it,expect} from 'vitest';
import {blockTable} from './models';
describe('prefix blocks',()=>{
 it('only reuses full matching sixteen-token blocks',()=>{
  const previous=Array.from({length:32},(_,i)=>String(i));
  const current=[...previous.slice(0,16),'changed',...previous.slice(17)];
  const blocks=blockTable(current,previous);
  expect(blocks.map(b=>b.cached)).toEqual([true,false]);
 });
});

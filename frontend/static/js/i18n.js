/* Offline interface localization. User documents and form values are never rewritten. */
(() => {
  const catalog = window.TALENTSOUK_TRANSLATIONS || {fr:{},ar:{}};
  let language = ['en','fr','ar'].includes(window.APP_LANGUAGE) ? window.APP_LANGUAGE : 'en';
  const texts = new WeakMap();
  const attributes = new WeakMap();
  const normalize = value => String(value || '').replace(/\s+/g,' ').trim();
  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const variables = /{{.*?}}|\$\{.*?\}/g;
  const dictionaries = {}, reverse = new Map(), patterns = [];
  for (const locale of ['en','fr','ar']) {
    dictionaries[locale] = new Map(Object.entries(catalog[locale] || {}).map(([key,value])=>[normalize(key),value]));
  }
  const keys = new Set([...dictionaries.fr.keys(),...dictionaries.ar.keys()]);
  const foldedKeys=new Map([...keys,...dictionaries.en.keys()].map(key=>[key.toLocaleLowerCase('en'),key]));
  for (const key of keys) {
    for (const locale of ['fr','ar']) {
      const value = dictionaries[locale].get(key);
      if (value && !reverse.has(normalize(value))) reverse.set(normalize(value),key);
    }
    const tokens = key.match(variables);
    if (!tokens) continue;
    const parts = key.split(variables);
    if (parts.join('').trim().length < 3) continue;
    const targets = {en:key,fr:dictionaries.fr.get(key),ar:dictionaries.ar.get(key)};
    // Translate a rendered UI sentence while preserving every variable verbatim.
    patterns.push({expression:new RegExp('^'+parts.map(escape).join('(.+?)')+'$'),tokens,targets});
  }
  patterns.sort((a,b)=>b.expression.source.length-a.expression.source.length);
  function translate(value) {
    const source = normalize(value);
    const canonical = reverse.get(source) || foldedKeys.get(source.toLocaleLowerCase('en')) || source;
    const exact = dictionaries[language].get(canonical);
    if (exact) return exact;
    if (language === 'en' && keys.has(canonical)) return canonical;
    const numbered=canonical.match(/^(\d+\.\s+)(.+)$/);
    if(numbered){const result=translate(numbered[2]);if(result!==numbered[2])return numbered[1]+result;}
    for(const [key,target] of dictionaries[language]) {
      if (/[:·]$/.test(key) && canonical.startsWith(key+' ')) return target+' '+canonical.slice(key.length+1);
    }
    for (const pattern of patterns) {
      const match = canonical.match(pattern.expression);
      const target = pattern.targets[language];
      if (!match || !target) continue;
      return target.replace(variables,token=>match[pattern.tokens.indexOf(token)+1]);
    }
    return value;
  }
  function protectedNode(node) {
    const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    if (!element) return true;
    if (element.closest('script,style,textarea,pre,code,[data-i18n-skip],[translate="no"]')) return true;
    const option = element.closest('option');
    if (option && option.value && option.closest('select[id*="company"],select[id*="job"],select[id*="offer"]')) return true;
    return false;
  }
  function translateTextNode(node) {
    if (protectedNode(node)) return;
    const value=node.nodeValue;
    if (!value || !normalize(value)) return;
    const previous=texts.get(node);
    const source=previous && value===previous.result ? previous.source : value;
    const trimmed=normalize(source);
    const translated=translate(trimmed);
    const result=translated===trimmed ? source : source.replace(source.trim(),translated);
    texts.set(node,{source,result});
    if (node.nodeValue!==result) node.nodeValue=result;
  }
  function translateAttributes(element) {
    if (protectedNode(element) && element.tagName!=='TEXTAREA') return;
    const previous=attributes.get(element)||{};
    for (const name of ['placeholder','title','aria-label','alt','data-label']) {
      if (!element.hasAttribute(name)) continue;
      const current=element.getAttribute(name);
      const old=previous[name];
      const source=old && current===old.result ? old.source : current;
      const result=translate(source);
      previous[name]={source,result};
      if (current!==result) element.setAttribute(name,result);
    }
    if (element.matches('input[type="submit"],input[type="button"]')) {
      const current=element.value, old=previous.value;
      const source=old && current===old.result ? old.source : current;
      const result=translate(source);previous.value={source,result};
      if(current!==result)element.value=result;
    }
    attributes.set(element,previous);
  }
  function translateNode(root) {
    if (root.nodeType===Node.TEXT_NODE) {translateTextNode(root);return;}
    if(root.nodeType===Node.ELEMENT_NODE && root.tagName==='TEXTAREA'){translateAttributes(root);return;}
    if (root.nodeType!==Node.ELEMENT_NODE || protectedNode(root)) return;
    translateAttributes(root);
    for (const child of root.childNodes) translateNode(child);
  }
  let observer;
  function applyLanguage(next) {
    if (!['en','fr','ar'].includes(next)) return;
    language=next;window.APP_LANGUAGE=next;
    document.documentElement.lang=next;
    document.documentElement.dir=next==='ar'?'rtl':'ltr';
    if(observer)observer.disconnect();
    translateNode(document.body);
    translateNode(document.querySelector('title'));
    document.querySelectorAll('#language-selector,#settings-language').forEach(select=>{select.value=next;});
    if(observer)observe();
    document.querySelectorAll('#draft-language,#summary-language,#cover-letter-language,#apply-language,#whatsapp-language').forEach(select=>{select.value=next;});
    document.dispatchEvent(new CustomEvent('app:languagechange',{detail:{language:next}}));
  }
  function observe() {
    observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label','alt','data-label']});
  }
  window.translateText=translate;
  window.setAppLanguage=applyLanguage;
  applyLanguage(language);
  observer=new MutationObserver(mutations=>{
    observer.disconnect();
    for(const mutation of mutations) {
      if(mutation.type==='characterData')translateTextNode(mutation.target);
      else if(mutation.type==='attributes')translateAttributes(mutation.target);
      else mutation.addedNodes.forEach(translateNode);
    }
    observe();
  });
  observe();
  const charts=new WeakMap();
  function localizeCharts() {
    if(!window.Chart || !window.Chart.instances)return;
    for(const chart of Object.values(window.Chart.instances)) {
      if(!chart.data)continue;
      let source=charts.get(chart);
      if(!source){source={labels:[...(chart.data.labels||[])],datasets:chart.data.datasets.map(dataset=>dataset.label)};charts.set(chart,source);}
      chart.data.labels=source.labels.map(label=>typeof label==='string'?translate(label):label);
      chart.data.datasets.forEach((dataset,index)=>{if(source.datasets[index])dataset.label=translate(source.datasets[index]);});
      chart.options.locale=language;
      if(chart.options.plugins?.legend)chart.options.plugins.legend.rtl=language==='ar';
      if(chart.options.plugins?.tooltip)chart.options.plugins.tooltip.rtl=language==='ar';
      chart.update('none');
    }
  }
  document.addEventListener('app:languagechange',localizeCharts);
  document.addEventListener('DOMContentLoaded',localizeCharts);
  // Browser dialogs are outside the DOM: localize their UI messages explicitly.
  for (const method of ['alert','confirm']) {
    const original=window[method].bind(window);
    window[method]=message=>original(translate(String(message)));
  }
})();

'use strict';
document.getElementById('size').addEventListener('change',event=>{
  const [width,height]=event.target.value.split('×').map(Number);
  const frame=document.getElementById('preview');frame.width=width;frame.height=height;
});

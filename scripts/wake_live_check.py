"""Short, opt-in wake diagnostic. Never saves audio or arbitrary recognized speech."""
import argparse,json,math,time
from pathlib import Path
from voice.audio_input import AudioInput
from voice.stt import VoskModel
from voice.wake_word import VoskWakeWord
from core.config import load_config

p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=25);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
c=load_config();model=VoskModel(Path(c['_resource_root'])/c['voice']['model_path']).load();wake=VoskWakeWord(model,c['voice']['sample_rate']);events=[];levels=[];errors=[]
audio=AudioInput(device=c['voice']['device'],sample_rate=c['voice']['sample_rate'],blocksize=c['voice']['sample_rate']//20,on_error=errors.append)
print('READY: говорите Сириус; запись не сохраняется.',flush=True)
audio.start();started=time.monotonic();generation=None;accepted=0
try:
 while time.monotonic()-started < args.seconds:
  frame=audio.read(.05)
  if frame is None: continue
  if frame.generation != generation: wake.reset();generation=frame.generation
  s=memoryview(frame.pcm).cast('h');rms=math.sqrt(sum(int(v)**2 for v in s)/max(1,len(s)))/32768;levels.append(rms)
  hit=wake.feed(frame.pcm)
  if hit:accepted+=1
  result=wake.last_result
  if result is not None:
   verify=wake.last_verification
   allowed={'сириус','сири','сириусу','сириусе','сирия','сервис','серия','серьёз','серьез','серьезно','серьёзно'}
   item={'second':round(time.monotonic()-started,2),'accepted':hit,'candidate':result.text if result.text in allowed else '<другое>','candidate_confidence':round(result.confidence,3),'candidate_duration':round(sum(w.duration for w in result.words),3),'verification':None if verify is None else (' '.join(w.text if w.text in allowed else '<другое>' for w in verify.words)),'verification_confidence':None if verify is None else round(verify.confidence,3),'pcm_rms':round(rms,4)}
   events.append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
finally:audio.stop()
report={'seconds':round(time.monotonic()-started,2),'device':c['voice']['device'],'accepted':accepted,'frames':len(levels),'rms_max':max(levels,default=0),'rms_mean':sum(levels)/max(1,len(levels)),'dropped_blocks':audio.dropped_blocks,'errors':errors,'events':events,'audio_saved':False};args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False),flush=True)

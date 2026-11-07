"""Short local questions spoken while voice capture is in the processing state."""
import logging

LOG = logging.getLogger('sirius.voice')


def speak_question(text):
    import pythoncom
    from win32com.client import Dispatch

    pythoncom.CoInitialize()
    try:
        voice = Dispatch('SAPI.SpVoice')
        russian = voice.GetVoices('Language=419')
        if russian.Count:
            voice.Voice = russian.Item(0)
        voice.Speak(text, 1)  # async so an unavailable audio endpoint cannot hold listening open
        if not voice.WaitUntilDone(3500):
            voice.Speak('', 3)  # purge
    except Exception as exc:
        LOG.warning('Local question speech unavailable: %s', type(exc).__name__)
    finally:
        pythoncom.CoUninitialize()

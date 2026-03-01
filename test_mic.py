"""Quick mic test — records 3 seconds and plays back. If you hear yourself, mic works."""
import pyaudio
import wave
import tempfile
import os

RATE = 16000
CHANNELS = 1
CHUNK = 1024
SECONDS = 3

pa = pyaudio.PyAudio()

# List devices
print("Audio devices:")
for i in range(pa.get_device_count()):
    info = pa.get_device_info_by_index(i)
    if info["maxInputChannels"] > 0:
        print(f"  IN  [{i}] {info['name']} (channels: {info['maxInputChannels']})")
    if info["maxOutputChannels"] > 0:
        print(f"  OUT [{i}] {info['name']} (channels: {info['maxOutputChannels']})")

default_in = pa.get_default_input_device_info()
default_out = pa.get_default_output_device_info()
print(f"\nDefault input:  [{default_in['index']}] {default_in['name']}")
print(f"Default output: [{default_out['index']}] {default_out['name']}")

print(f"\nRecording {SECONDS}s from mic... SPEAK NOW!")
stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS, rate=RATE,
                 input=True, frames_per_buffer=CHUNK)
frames = []
for _ in range(int(RATE / CHUNK * SECONDS)):
    data = stream.read(CHUNK, exception_on_overflow=False)
    frames.append(data)

# Check if we got any non-silent audio
import struct
all_samples = struct.unpack(f"<{len(b''.join(frames))//2}h", b"".join(frames))
max_vol = max(abs(s) for s in all_samples)
avg_vol = sum(abs(s) for s in all_samples) / len(all_samples)
print(f"Max volume: {max_vol}/32768  Avg volume: {avg_vol:.0f}/32768")
if max_vol < 100:
    print("WARNING: Mic appears SILENT — check macOS Privacy > Microphone > Terminal")
else:
    print("Mic is capturing audio OK")

stream.stop_stream()
stream.close()

print("Playing back...")
stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS, rate=RATE,
                 output=True, frames_per_buffer=CHUNK)
for f in frames:
    stream.write(f)
stream.stop_stream()
stream.close()
pa.terminate()
print("Done.")

FROM openvoiceos/core:latest

RUN apt-get install -y portaudio19-dev libpulse-dev swig

COPY . /tmp/ovos-audio
RUN pip3 install /tmp/ovos-audio

USER mycroft

ENTRYPOINT mycroft-audio
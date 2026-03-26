# embedded-systems
Project for Embeded Systems class, in 2026

## Warstwa sprzętowa:
 - matryca led 64x64
 - controll panel, made from 4 buttons
 - raspberry pi pico 2W
 - dell thin-client wyse 3030

## Warstwa aplikacyjna:

### Zadania mikrokontrolera:
 - obsługa wyświetlania grafiki na matrycy led
 - obsługa pilota, przyciski:
   - do tyłu
   - pauza
   - do przodu
   - wyświetl kod QR
  
### Zadania thin-clienta
 - obsługa wifi-managera (uzyskanie hasła do wi-fi i podłączenie się do lokalnej sieci)
 - obsługa streamingu muzyki via spotify/youtube music
 - przekazywanie poleceń od mikrokontrolera do streamingu muzyki (stop, next, previous)
 - generowanie grafiki, kodu QR oraz przekazywanie do mikrokontrolera
 - wyświetlanie 

### Dodatkowe funkcjonalności
 - mikrokontroler z thin-clientem może być połączony kablem USB, lub komunikacja poprzez wi-fi (better user experience)
 - kod qr, będzie linkiem do adresu IP strony w lokalnej sieci wi-fi

### Tech stack
 - oprogramowanie mikrokontrolera w MicroPython/CPython
 - pozyskiwanie utworów odbędzie się za pośrednictwem spotDL - https://github.com/spotdl/spotify-downloader
 - skrypt do zarządzania pobraną muzyką, odtwarzaniem i przekazywaniem grafiki będzie w Ruby
 

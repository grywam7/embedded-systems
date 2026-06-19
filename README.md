# embedded-systems
Project for Embedded Systems class, 2026

## Warstwa sprzętowa:
- matryca led 64x64
-	control panel - 6 BUTTONS: PLAY/PAUSE, DISPLAY QR, VOLUME DOWN, VOLUME UP, NEXT SONG
-	raspberry pi pico 2W
-	dell thin-client wyse 3030 + karta wifi
-	głośniki + wzmacniacz 2x50W


## Warstwa aplikacyjna:

### Zadania mikrokontrolera:
- obsługa pilota
- odebranie kodu QR i grafiki z okładką utworu
- obsługa wyświetlania grafiki na matrycy LED

  
### Zadania thin-clienta
-	komunikacja serwera z mikrokontrolerem za pomocą USB
- generowanie kodu QR, który jest linkiem do adresu IP strony w lokalnej sieci WiFi
- obsługa wifi-managera (uzyskanie hasła do wi-fi i podłączenie się do lokalnej sieci)
- obsługa cache’owania muzyki via spotify/youtube 
- obsługa bazy w SQLite
- obsługa aplikacji internetowej do dodawania kolejnych piosenek i zarządzania odtwarzaniem
- przekazywanie poleceń od mikrokontrolera do odtwarzacza muzyki (stop, next, previous, volume up/down)
-	przekazywanie grafiki (QR i okładek piosenek) do mikrokontrolera



### Tech stack
- oprogramowanie mikrokontrolera w MicroPython
- pozyskiwanie utworów odbywa się za pośrednictwem biblioteki spotDL - https://github.com/spotdl/spotify-downloader
- odtwarzanie muzyki: MPG123
- serwer w RUBY (działający na dellu)
- dell: DEBIAN 12 bookworm

 

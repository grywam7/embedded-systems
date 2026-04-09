# embedded-systems
Project for Embeded Systems class, in 2026

## Warstwa sprzętowa:
 - matryca led 64x64
 - controll panel, made from 6 buttons or 1 button & joystick
 - raspberry pi pico 2W
 - dell thin-client wyse 3030

## Warstwa aplikacyjna:

### Zadania mikrokontrolera:
 - obsługa wyświetlania grafiki na matrycy led
 - obsługa pilota, przyciski:
   - do tyłu
   - pauza
   - do przodu
   - volume up
   - volume down
   - wyświetl kod QR

### Microkontroler
 - inicjalizujemy wyswietlacz i wyświetlamy jakąś grafike powitalną
 - co x sekund zainicjalizować komunikacje USB - porozumieć się z thin-clientem i odebrać odpowiedź o prawidłowym setupie
 - odebrac od serwera informaje że jest gotowy do działania
 - odebrać wygenerowany obrazek z kodem QR i zapisać sobie go w pamięci np. RAM
 - zaczyna sie główna pętla obsługi muzyki
   - odbieramy grafike z okładką utworu
   - obsługujemy przciski jako callbacki wysyłające wiadomośc po USB ([cokolwiek to znaczy](https://docs.micropython.org/en/latest/pyboard/tutorial/switch.html))
   - co x czasu wysyłamy wiadomość timeout czy dalej serwer działa, jeśli nie wyswietlamy obrazek errora
     - jak nie działa, to wracamy do etapu inicjalizacji i próbujemy go zrobić co x sekund
  
### Zadania thin-clienta
 - obsługa wifi-managera (uzyskanie hasła do wi-fi i podłączenie się do lokalnej sieci)
 - obsługa cachowania muzyki via spotify/youtube i baze w SQLite
 - przekazywanie poleceń od mikrokontrolera do odtwarzacza muzyki (stop, next, previous)
 - generowanie grafiki, kodu QR oraz przekazywanie do mikrokontrolera

### Dodatkowe funkcjonalności
 - mikrokontroler z thin-clientem może być połączony kablem USB, lub komunikacja poprzez wi-fi (better user experience)
 - kod qr, będzie linkiem do adresu IP strony w lokalnej sieci wi-fi

### Tech stack
 - oprogramowanie mikrokontrolera w MicroPython/CPython
 - pozyskiwanie utworów odbędzie się za pośrednictwem spotDL - https://github.com/spotdl/spotify-downloader
 - skrypt do zarządzania pobraną muzyką, odtwarzaniem i przekazywaniem grafiki będzie w Ruby
 

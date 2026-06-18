class UsbCommunicationService
  BAUD = 115200

  # Buttons on the Pico send "BTN:<n>\n"; map each to a MusicPlayerService command.
  BUTTON_COMMANDS = {
    '1' => 'PAUSE',
    '2' => 'NEXT',
    '3' => 'VOLUME_UP',
    '4' => 'VOLUME_DOWN'
  }.freeze

  # macOS exposes the Pico as /dev/cu.* (call-out, non-blocking on open).
  # Linux exposes it as /dev/ttyACM*. The /dev/tty.* device on macOS blocks
  # on open waiting for carrier detect, so it must NOT be used here.
  DEVICE_GLOBS = [
    '/dev/cu.usbmodem*',
    '/dev/ttyACM*'
  ].freeze

  def initialize(music_player_service)
    @music_player_service = music_player_service
    @write_mutex = Mutex.new
    @serial_port = open_port
    start_reader if @serial_port
  end

  def connected?
    !@serial_port.nil?
  end

  # Server -> Pico: stream a pre-packed 16 KB HUB75 framebuffer (length-prefixed).
  # Fire-and-forget: USB CDC is lossless, so no application-level ACK is required.
  def send_cover_image(id, path)
    return unless @serial_port

    data = File.binread(path)
    @write_mutex.synchronize do
      @serial_port.write("IMG:#{id}:#{data.bytesize}\n")
      @serial_port.write(data)
      @serial_port.flush
    end
  end

  def send_message(message)
    return unless @serial_port

    @write_mutex.synchronize do
      @serial_port.write(message)
      @serial_port.flush
    end
  end

  private

  def open_port
    path = DEVICE_GLOBS.flat_map { |glob| Dir.glob(glob) }.first
    unless path
      warn '[usb] no Pico serial device found - running without USB'
      return nil
    end

    SerialPort.new(path, BAUD, 8, 1, SerialPort::NONE).tap do
      warn "[usb] connected on #{path}"
    end
  rescue StandardError => e
    warn "[usb] could not open serial port: #{e.message} - running without USB"
    nil
  end

  # A single thread owns all reads from the port. It reads complete lines
  # (every Pico -> server message is newline-terminated) and dispatches them.
  # This is the ONLY reader, which avoids races with the image-sending path.
  def start_reader
    @reader = Thread.new do
      loop do
        line = @serial_port.gets
        if line.nil?
          sleep 0.1
          next
        end
        dispatch(line.chomp)
      rescue IOError, EOFError => e
        warn "[usb] reader error: #{e.message}"
        sleep 0.5
      end
    end
  end

  def dispatch(line)
    return if line.empty?

    if line.start_with?('BTN:')
      command = BUTTON_COMMANDS[line.split(':', 2).last.strip]
      if command
        warn "[usb] #{line} -> #{command}"
        @music_player_service.execute_command(command)
      end
    elsif line.start_with?('CMD:')
      @music_player_service.execute_command(line.split(':', 2).last.strip)
    end
    # "OK" / "OK:<id>" image acks (and REPL banner noise) are ignored.
  end
end

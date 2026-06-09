class UsbCommunicationService

#set_modem_params(baud, data_bits, stop_bits, parity)
#   baud [Integer] the baud rate
#   data_bits [Integer] the number of data bits
#   stop_bits [Integer] the number of stop bits
#   parity [Integer] the type of parity checking
  
  def initialize(music_player_service)

    return 0

    _baud = 115200
    _data_bits = 8
    _stop_bits = 1
    _parity = SerialPort::NONE

    # binding.pry

    ["/dev/tty.usbmodem14201"].each do |path|
      begin
        next unless Dir.glob(path).first
        @serial_port = SerialPort.open(Dir.glob(path).first, _baud, _data_bits, _stop_bits, _parity)
        test_connection
        break
      rescue
      end
    end

    @serial_port = SerialPort.new(0)
    @music_player_service = music_player_service
  end


  def read_message
    begin
      _message = @serial_port.read_nonblock(4096)
      if _message.include?('COMMAND:')
        @music_player_service.execute_command(_message.split('COMMAND:').last.strip)
      else
        return _message
      end
    rescue IO::WaitReadable
    end
  end

  def send_cover_image(id, path)
    data = File.binread(path)
    @serial_port.write("IMG:#{id}:#{data.bytesize}\n")
    @serial_port.write(data)
    @serial_port.flush
    @serial_port.gets.strip   # "OK" / "ERR"
  end


  def send_message(message)
    @serial_port.write(message)
    @serial_port.flush
  end

  def test_connection
    send_message('HELLO')
    sleep 1
    raise 'Connection test failed' unless read_message == 'HI'
  end
end
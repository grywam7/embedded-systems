require 'socket'
require 'rqrcode'

# Builds a 64x64 HUB75 framebuffer (the same 8-bitplane format as the song
# covers) showing a QR code for this server's own web UI, so a phone can scan it
# and add songs without anyone hunting for the IP.
#
# The QR is rendered "dark modules off, background lit": the panel lights white
# and the QR modules are the unlit pixels -> high contrast dark-on-light, which
# is what phone scanners expect.
class QrService
  GAMMA_LUT = (0..255).map { |v| ((v / 255.0)**2.2 * 255).round.clamp(0, 255) }.freeze
  SIZE = 64

  def initialize(port: 4567, host: nil)
    @port = port
    @host = host
  end

  def url
    # Uppercase scheme: URI schemes are case-insensitive, so this still opens as a
    # normal link, but "HTTP://1.2.3.4:5" is entirely alphanumeric -> the QR uses the
    # dense alphanumeric mode -> fewer modules -> bigger, easier-to-scan squares.
    "HTTP://#{@host || local_ip}:#{@port}"
  end

  # 16384 bytes, ready to ship over the same IMG: channel as a cover.
  def framebuffer
    pack(render(modules))
  end

  private

  # The LAN address used to reach the network (no packet is actually sent).
  def local_ip
    s = UDPSocket.new
    s.connect('8.8.8.8', 1)
    s.addr.last
  rescue StandardError
    '127.0.0.1'
  ensure
    s&.close
  end

  # 2D array, true = dark module. level :l keeps the module count (density) low.
  def modules
    RQRCodeCore::QRCode.new(url, level: :l).modules
  end

  # Paint the QR into a 64x64 RGB buffer: white background, dark modules black,
  # centered with the largest integer module size that leaves a quiet border.
  def render(mods)
    n = mods.size
    # Largest integer module size that fits; the panel's dark frame is the quiet zone.
    scale = [SIZE / n, 1].max
    off = (SIZE - n * scale) / 2
    rgb = ("\xFF".b * (SIZE * SIZE * 3)) # all white (lit)
    mods.each_with_index do |row, my|
      row.each_with_index do |dark, mx|
        next unless dark
        scale.times do |dy|
          py = off + my * scale + dy
          next unless py.between?(0, SIZE - 1)
          scale.times do |dx|
            px = off + mx * scale + dx
            next unless px.between?(0, SIZE - 1)
            i = (py * SIZE + px) * 3
            rgb.setbyte(i, 0); rgb.setbyte(i + 1, 0); rgb.setbyte(i + 2, 0)
          end
        end
      end
    end
    rgb
  end

  # Identical bitplane layout to MusicDownloaderService#create_thumbnail (proven
  # on the panel): 8 planes x 2048 bytes, half-select shift, R/B channel order.
  def pack(rgb)
    planes = Array.new(8) { ("\x00".b * 2048) }
    SIZE.times do |y|
      shift = ((y >> 5) & 1) * 3
      mask  = 0b111 << shift
      row_off = (31 - (y & 31)) * 64
      SIZE.times do |x|
        i = (y * SIZE + x) * 3
        r = GAMMA_LUT[rgb.getbyte(i)]
        g = GAMMA_LUT[rgb.getbyte(i + 1)]
        b = GAMMA_LUT[rgb.getbyte(i + 2)]
        bidx = x + row_off
        8.times do |bp|
          bit = 1 << bp
          bits = ((b & bit) >> bp) << 2 | ((g & bit) >> bp) << 1 | ((r & bit) >> bp)
          plane = planes[bp]
          plane.setbyte(bidx, (plane.getbyte(bidx) & ~mask) | ((bits << shift) & 0xFF))
        end
      end
    end
    planes.join
  end
end

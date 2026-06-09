class MusicDownloaderService

  GAMMA_LUT = (0..255).map { |v| ((v / 255.0)**2.2 * 255).round.clamp(0, 255) }.freeze

  def initialize(song_url)
    @song_url = song_url
    @song = nil
    # TO DO:
    # -> change this servie to async, so it doesn't block web server while downloading.
    # -> when spotDL fails to download song - we might be lucky using metadata to download it via yt-dlp
    # -> but, as this process takes time, we need to somehow inform user his request failed 
    # -> so maybe in scheduled song just display it in RED colors, with error message
    # _thread = Thread.new do
    return download_spotify if @song_url.include?('spotify')
    return download_other
    # end
    # _thread.abort_on_exception = true
  end

  def download_spotify
    ## download song metadata
    _metadata_extraction = %x{
      source venv/bin/activate
      spotdl save #{@song_url} --save-file song_metadata.spotdl
    }

    return 'unknown' if _metadata_extraction.include?('LookupError: No results found for song')
    
    ## check if song already exists in db, if not create it
    _metadata_file = File.open('song_metadata.spotdl', 'r').read
    _song_metadata = JSON.parse(_metadata_file).first

    @song = Song.first_or_create(
      title: _song_metadata['name'],
      artist: _song_metadata['artists'].join(', '),
      album: _song_metadata['album_name'],
      duration: _song_metadata['duration']
    )

    ## try to find music file, if it doesn't exist, download it & extract cover image
    begin
      File.open("#{@song.music_path}", 'r')
    rescue Errno::ENOENT
      _download_result = %x{
        source venv/bin/activate
        spotdl --web-use-output-dir --output music_data download #{@song_url}
      }

      if _download_result.include?('LookupError: No results found for song')
        @song&.destroy
        return 'unknown'
      end
      
      create_thumbnail
    end

    @song.update(is_ready: true)
    return @song.id
  end

  def extract_image
    _cover_image_path = "#{Dir.pwd}/public/cover_images/#{@song.id}.jpg"
    _image = ''
    TagLib::MPEG::File.open("#{@song.music_path}") do |mp3|
      File.open(_cover_image_path, 'wb') do |file|
        _image = mp3.id3v2_tag.frame_list('APIC').first.picture
        file << _image
      end
    end
    _image
  end

  def rgb_64x64_thumbnail
    @rgb_64x64_thumbnail ||= Vips::Image.thumbnail_buffer(extract_image, 64, height: 64).colourspace('srgb').extract_band(0, n: 3).write_to_memory
  end

  # Packs a 64x64 RGB image into the HUB75 bitplane-sliced framebuffer format
  # consumed by client/hub75.py#load_frame — 8 bitplanes x 2048 bytes = 16384 bytes.
  # Matches set_pixel's byte layout and the channel swap from load_bmp.
  def create_thumbnail
    rgb_64x64_thumbnail
    Thread.new do
      _bin_path = "#{Dir.pwd}/public/cover_images_bin/#{@song.id}.bin"
      _planes = Array.new(8) { ("\x00".b * 2048) }

      64.times do |y|
        _shift = ((y >> 5) & 1) * 3
        _mask  = 0b111 << _shift
        _row_offset = (31 - (y & 31)) * 64

        64.times do |x|
          _i = (y * 64 + x) * 3
          _r = GAMMA_LUT[rgb_64x64_thumbnail.getbyte(_i)]
          _g = GAMMA_LUT[rgb_64x64_thumbnail.getbyte(_i + 1)]
          _b = GAMMA_LUT[rgb_64x64_thumbnail.getbyte(_i + 2)]
          _byte_index = x + _row_offset

          8.times do |bp|
            _bit  = 1 << bp
            # Channel swap mirrors load_bmp's call to set_pixel(x, y, g, b, r, ...):
            # bit2 = blue, bit1 = green, bit0 = red.
            _bits = ((_b & _bit) >> bp) << 2 |
                    ((_g & _bit) >> bp) << 1 |
                    ((_r & _bit) >> bp)
            _plane = _planes[bp]
            _plane.setbyte(_byte_index, (_plane.getbyte(_byte_index) & ~_mask) | ((_bits << _shift) & 0xFF))
          end
        end
      end

      File.binwrite(_bin_path, _planes.join)
    end
    return true
  end


  def download_other

  end

end
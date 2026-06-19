class MusicDownloaderService

  GAMMA_LUT = (0..255).map { |v| ((v / 255.0)**2.2 * 255).round.clamp(0, 255) }.freeze

  def initialize(song_url)
    @song_url = song_url
    @song = nil
  end

  # --- Step 1: verification (synchronous, runs inside the web request) ---
  # Looks up the song's metadata and registers a pending Song. Returns the
  # Song (status 'pending') if it is downloadable, or :not_found / :error.
  # The heavy audio download is deferred to #download! via the queue worker.
  def verify
    return verify_spotify if @song_url.include?('spotify')
    # yt-dlp / other providers are not supported yet.
    :error
  end

  def verify_spotify
    ## fetch song metadata only (cheap, no audio download). Quote the URL so
    ## Spotify's ?si=...&... query params don't get mangled by the shell.
    _metadata_extraction = %x{
      venv/bin/spotdl save "#{@song_url}" --save-file song_metadata.spotdl 2>&1
    }

    return :not_found if _metadata_extraction.include?('No results found')

    ## spotdl writes an empty list ([]) when it found nothing / the URL is the wrong
    ## type, so guard before indexing into the metadata.
    return :not_found unless File.exist?('song_metadata.spotdl')
    _song_metadata = JSON.parse(File.read('song_metadata.spotdl')).first
    return :not_found if _song_metadata.nil?

    ## check if song already exists in db, if not create it (status defaults to 'pending')
    @song = Song.first_or_create(
      title: _song_metadata['name'],
      artist: _song_metadata['artists'].join(', '),
      album: _song_metadata['album_name'],
      duration: _song_metadata['duration']
    )
    @song
  rescue StandardError => e
    warn "[downloader] verify failed: #{e.message}"
    :error
  end

  # --- Step 2: download (heavy, runs in the background queue worker) ---
  # Downloads the audio file and builds the cover thumbnail, then flips the
  # song to ready. Any failure marks it failed with a user-facing message.
  def download!(song)
    @song = song
    @song.update(status: 'downloading')

    ## download the audio only if the file isn't on disk yet (mp3 is keyed by
    ## artist/title, so it may already exist from a different song id)
    unless File.exist?(@song.music_path)
      _download_result = %x{
        venv/bin/spotdl --web-use-output-dir --output music_data download "#{@song_url}" 2>&1
      }

      if _download_result.include?('No results found')
        @song.update(status: 'failed', error_message: 'Could not download this song, try a different provider.')
        return false
      end
    end

    unless File.exist?(@song.music_path)
      @song.update(status: 'failed', error_message: 'Download produced no audio file.')
      return false
    end

    ## ALWAYS build the cover for THIS song id — covers are keyed by id, so a song
    ## whose mp3 already existed (under another id) still needs its own id.jpg/.bin.
    create_thumbnail

    @song.update(status: 'ready', is_ready: true)
    true
  rescue StandardError => e
    warn "[downloader] download failed: #{e.message}"
    @song&.update(status: 'failed', error_message: e.message)
    false
  end

  # Returns the embedded cover bytes, or nil if the mp3 has no ID3v2 tag / no APIC
  # frame (some downloads have no artwork) -> caller then skips the panel thumbnail.
  def extract_image
    _image = nil
    TagLib::MPEG::File.open("#{@song.music_path}") do |mp3|
      _apic = mp3.id3v2_tag&.frame_list('APIC')&.first
      _image = _apic&.picture
    end
    return nil unless _image
    File.binwrite("#{Dir.pwd}/public/cover_images/#{@song.id}.jpg", _image)
    _image
  end

  def rgb_64x64_thumbnail
    return @rgb_64x64_thumbnail if defined?(@rgb_64x64_thumbnail)
    _img = extract_image
    @rgb_64x64_thumbnail = _img &&
      Vips::Image.thumbnail_buffer(_img, 64, height: 64).colourspace('srgb').extract_band(0, n: 3).write_to_memory
  end

  # Packs a 64x64 RGB image into the HUB75 bitplane-sliced framebuffer format
  # consumed by client/hub75.py#load_frame — 8 bitplanes x 2048 bytes = 16384 bytes.
  # Matches set_pixel's byte layout and the channel swap from load_bmp.
  def create_thumbnail
    return false unless rgb_64x64_thumbnail   # no embedded cover -> skip; song still plays
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

end
class MusicDownloaderService

  def initialize(song_url)
    @song_url = song_url
    # ten thread zupełnie nic nie robi - to bardziej idea na przyszłosć żeby to był serwis co biega w tle jak music_player_service
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

    _song = Song.first_or_create(
      title: _song_metadata['name'],
      artist: _song_metadata['artists'].join(', '),
      album: _song_metadata['album_name'],
      duration: _song_metadata['duration']
    )
    _song_path = "#{Dir.pwd}/music_data/#{_song_metadata['artists'].join(', ')} - #{_song_metadata['name']}"

    ## try to find music file, if it doesn't exist, download it & extract cover image
    begin
      File.open("#{_song_path}.mp3", 'r')
    rescue Errno::ENOENT
      _download_result = %x{
        source venv/bin/activate
        spotdl --web-use-output-dir --output music_data download #{@song_url}
      }

      if _download_result.include?('LookupError: No results found for song')
        _song&.destroy
        return 'unknown'
      end
      
      extract_cover_image(_song.id, _song_path)
      resize_cover_image_to_64px(_song.id)
    end

    _song.update(is_ready: true)
    return _song.id
  end

  def extract_cover_image(song_id, song_path)
    _cover_image_path = "#{Dir.pwd}/public/cover_images/#{song_id}.jpg"

    TagLib::MPEG::File.open("#{song_path}.mp3") do |mp3|
      _cover = mp3.id3v2_tag.frame_list('APIC').first.picture
      File.open(_cover_image_path, 'wb') {|f| f << _cover}
    end
  end

  def resize_cover_image_to_64px(song_id)
    _cover_image_path = "#{Dir.pwd}/public/cover_images_64px/#{song_id}.jpg"
    _original_image_path = "#{Dir.pwd}/public/cover_images/#{song_id}.jpg"

    Vips::Image.thumbnail(_original_image_path, 64, height: 64).write_to_file(_cover_image_path)
  end


  def download_other

  end

end
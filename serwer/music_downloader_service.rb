class MusicDownloaderService

  def initialize(song_url)
    @song_url = song_url
  end

  def download_spotify
    ## download song metadata
    %x{
      source venv/bin/activate
      spotdl save #{@song_url} --save-file song_metadata.spotdl
    }
    
    ## check if song already exists in db, if not create it
    _metadata_file = File.open('song_metadata.spotdl', 'r').read
    _song_metadata = JSON.parse(_metadata_file).first

    _song = Song.first_or_create(
      title: _song_metadata['name'],
      artist: _song_metadata['artist'],
      album: _song_metadata['album_name'],
      duration: _song_metadata['duration']
    )

    _root_dir = "/Users/sbrzozowski/School/embedded-systems/serwer/"
    _music_path = "#{_root_dir}music_data/#{_song_metadata['artist']} - #{_song_metadata['name']}"
    _cover_image_path = "#{_root_dir}public/cover_images/#{_song.id}.jpg"

    ## try to find music file, if it doesn't exist, download it & extract cover image
    begin
      File.open("#{_music_path}.mp3", 'r')
    rescue Errno::ENOENT
      %x{
        source venv/bin/activate
        spotdl --web-use-output-dir --output music_data download #{@song_url}
      }
      puts "Extracting cover image from downloaded file..."
      
      TagLib::MPEG::File.open("#{_music_path}.mp3") do |mp3|
        cover = mp3.id3v2_tag.frame_list('APIC').first.picture
        File.open(_cover_image_path, 'wb') {|f| f << cover}
      end
    end

    return _song.id
  end

  def download_other

  end

end
class MusicPlayerService
  attr_reader :volume

  def initialize
    @fifo_path = "#{Dir.pwd}/tmp/mpg123.fifo"
    @volume = 50
    FileUtils.mkdir_p(File.dirname(@fifo_path))
    system("mkfifo", @fifo_path) unless File.exist?(@fifo_path)

    @music_player_cli = IO.popen("mpg123 -R --fifo #{@fifo_path}", "r+")

    # wait for music player to initialize
    sleep 3
    File.open(@fifo_path, 'w') { |f| f.puts "SILENCE\n V 50" }
    Thread.new { play_loop }
  end

  #TO DO
  # ->button "PREVIOS" - if we change Schedule, to have flag "played" instead of removingi it, we can have history of played songs
  # -> so previos wold be find next song with flag payed false, and for songs id - 2 & id - 1, set played to false, and send STOP 
  # -> command, so it will stop current ad find id-2 as next song to play
  def execute_command(command)
    if command == 'PAUSE'
      File.open(@fifo_path, 'w') { |f| f.puts "P" }
    elsif command == 'NEXT'
      File.open(@fifo_path, 'w') { |f| f.puts "S" }
    elsif command == 'VOLUME_UP'
      @volume = [@volume + 5, 100].min
      File.open(@fifo_path, 'w') { |f| f.puts "V #{@volume}" }
    elsif command == 'VOLUME_DOWN'
      @volume = [@volume - 5, 0].max
      File.open(@fifo_path, 'w') { |f| f.puts "V #{@volume}" }
    end
  end

  private

  def schedule(song)
    File.open(@fifo_path, 'w') { |f| f.puts "L #{path_for(song)}"}
  end

  def play_loop
    loop do
      _message = @music_player_cli.gets
      if _message =~ /@P 0|@SILENCE/
        while Schedule.first&.song&.is_ready != true
          sleep 0.5
        end
        schedule(Song.get(Schedule.first.song_id))
        Schedule.first.destroy
      end
      sleep 0.2
    rescue e
      warn e.full_message
    end
  end

  def path_for(song)
    "#{Dir.pwd}/music_data/#{song.artist} - #{song.title}.mp3"
  end
end
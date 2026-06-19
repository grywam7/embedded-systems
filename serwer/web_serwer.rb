require 'sinatra'
require 'haml'
require 'data_mapper'
require 'json/pure'
require 'taglib'
require 'thread'
require 'vips'
require 'serialport'

#development
require 'pry'

DataMapper::setup(:default, "sqlite3://#{Dir.pwd}/music.db")
require_relative 'models/schedule'
require_relative 'models/song'
require_relative 'services/music_downloader_service'
require_relative 'services/download_queue_service'
require_relative 'services/music_player_service'
require_relative 'services/usb_communication_service'
DataMapper.finalize
Song.auto_upgrade!
Schedule.auto_upgrade!

Schedule.all.destroy # clear schedule on server start

Song.all.each do |song| # clear songs that are not ready, to avoid errors with missing files
  song.destroy
end


configure do
  set :music_player_service, MusicPlayerService.new()
  set :usb_communication_service, UsbCommunicationService.new(settings.music_player_service)
  # let the player push a song's cover to the panel when it starts
  settings.music_player_service.usb_communication_service = settings.usb_communication_service
  set :download_queue_service, DownloadQueueService.new
end

get '/auth' do # Authentication of wi-fi connection
  haml :auth
end

get '/' do # Display, input form
  @schedule = Schedule.all :order => :id.asc
  @volume = settings.music_player_service.volume
  @alert = params['alert'] # carried across the POST -> redirect so the ack shows

  haml :index
end

get '/playlist' do # send playlist as json
  Schedule.all.to_json
end

post '/song/new' do # verify the song, then acknowledge and download in the background
  _song_url = request.params['song_url'].strip
  _song_url.prepend('https://') if _song_url !~ /http/i

  # Cheap, synchronous metadata lookup decides whether the song is downloadable.
  _result = MusicDownloaderService.new(_song_url).verify

  _alert =
    case _result
    when :not_found then 'unknown'
    when :error then 'error'
    else
      # Verified -> show it on the schedule now and download off the request path.
      Schedule.create(song_id: _result.id)
      if _result.status == 'ready'
        'success' # already on disk (e.g. re-added), nothing to download
      else
        settings.download_queue_service.enqueue(_result.id, _song_url)
        'queued'
      end
    end

  redirect "/?alert=#{_alert}", 303
end

get '/player/pause' do
  settings.music_player_service.execute_command('PAUSE')
  redirect '/', 303
end

get '/player/next' do
  settings.music_player_service.execute_command('NEXT')
  redirect '/', 303
end

get '/player/volume_up' do
  settings.music_player_service.execute_command('VOLUME_UP')
  redirect '/', 303
end

get '/player/volume_down' do
  settings.music_player_service.execute_command('VOLUME_DOWN')
  redirect '/', 303
end

get '/qr' do                      # test trigger: push a QR of this server's URL to the panel
  settings.usb_communication_service.show_qr
  redirect '/', 303
end

delete '/song/:id' do |id| # delete song from schedule
  Schedule.get(id).destroy
  @alert = 'successfuly_deleted'
  @schedule = Schedule.all :order => :id.asc
  haml :index
end
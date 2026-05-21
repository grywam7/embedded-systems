require 'sinatra'
require 'Haml'
require 'data_mapper'
require 'pry'
require 'json/pure'
require 'taglib'
require 'thread'
require 'vips'

DataMapper::setup(:default, "sqlite3://#{Dir.pwd}/music.db")
require_relative 'models/schedule'
require_relative 'models/song'
require_relative 'music_downloader_service'
require_relative 'music_player_service'

DataMapper.finalize
Song.auto_upgrade!
Schedule.auto_upgrade!

Schedule.all.destroy # clear schedule on server start


configure do
  set :music_player_service, MusicPlayerService.new()
end

get '/auth' do # Authentication of wi-fi connection
  haml :auth
end

get '/' do # Display, input form
  @schedule = Schedule.all :order => :id.asc
  @volume = settings.music_player_service.volume

  haml :index
end

get '/playlist' do # send playlist as json
  Schedule.all.to_json
end

post '/song/new' do # add new song to schedule
  # add to Schedule model, with flag is_ready = false
  _song_url = request.params['song_url'].strip
  _song_url.prepend('https://') if _song_url !~ /http/i

  # add to downloader -> it wold be best if it was async
  if _song_url.include?('spotify')
    _song_id = MusicDownloaderService.new(_song_url).download_spotify
  else
    _song_id = MusicDownloaderService.new(_song_url).download_other
  end

  if _song_id
    @alert = 'success'
    Schedule.create(song_id: _song_id)
  else
    @alert = _song_id
  end

  redirect '/', 303
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

delete '/song/:id' do |id| # delete song from schedule
  Schedule.get(id).destroy
  @alert = 'successfuly_deleted'
  @schedule = Schedule.all :order => :id.asc
  haml :index
end
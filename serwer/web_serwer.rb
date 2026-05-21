require 'sinatra'
require 'Haml'
require 'data_mapper'
require 'pry'
require 'json/pure'
require 'taglib'

DataMapper::setup(:default, "sqlite3://#{Dir.pwd}/music.db")
require_relative 'models/schedule'
require_relative 'models/song'
require_relative 'music_downloader_service'

DataMapper.finalize
Song.auto_upgrade!

Schedule.auto_upgrade!


get '/auth' do # Authentication of wi-fi connection
  haml :auth
end

get '/' do # Display, input form
  @schedule = Schedule.all :order => :id.asc

  haml :index
end

get '/playlist' do # send playlist as json
  Schedule.all.to_json
end

post '/song/new' do # add new song to schedule
  # dodaj do modelu Schedule
  _song_url = request.params['song_url'].strip
  _song_url.prepend('https://') if _song_url !~ /http/i

  # dodaj do kolejki do pobierania
  if _song_url.include?('spotify')
    _song_id = MusicDownloaderService.new(_song_url).download_spotify
  else
    _song_id = MusicDownloaderService.new(_song_url).download_other
  end

  if _song_id
    @alert = 'success'
    Schedule.create(song_id: _song_id)
  else
    @alert = 'error'
  end

  @schedule = Schedule.all :order => :id.asc

  haml :index
end

delete '/song/:id' do |id| # delete song from schedule
  Schedule.get(id).destroy
  @alert = 'successfuly_deleted'
  @playlist = Schedule.all :order => :id.asc
  haml :index
end
require 'sinatra'
require 'Haml'

get '/' do # Display, input form
  haml :index
end

get '/playlist' do # send playlist as json
  
end

post '/song/new' do # add new song to playlist

end

delete '/song/:id' do |id| # delete song from playlist
  
end